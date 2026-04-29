from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any

from screener.alerts import AlertSidecarError, build_daily_alert_document
from screener.alerts.state import load_alert_state, save_alert_state
from screener.alerts.writer import build_daily_alert_paths, write_alert_document
from screener.config import Settings
from screener.data import EarningsCalendarProvider, EarningsInfo
from screener.models import (
    CandidateResult,
    PipelineContext,
    RunArtifacts,
    RunMetadata,
    ScoreBreakdown,
    ScreenRunResult,
    TickerInput,
)
from screener.reporting.json_report import build_json_report
from screener.reporting.markdown import build_markdown_report
from screener.scoring import TierThresholds, classify_investability_tier, rank_candidates
from screener.storage.files import ensure_directory, write_json, write_text

from .context import fetch_benchmark_context, merge_benchmark_context, merge_earnings_context, normalize_generated_at
from .contracts import CandidateScorer, IndicatorEngine, MarketDataProvider, UniverseProvider
from .providers import (
    StaticUniverseProvider,
    TechnicalIndicatorEngine,
    build_earnings_calendar_provider,
    build_market_data_provider,
)
from .snapshot import INDICATOR_SNAPSHOT_SCHEMA_VERSION, _maybe_float, build_indicator_snapshot


class RankedCandidateScorer:
    def __init__(self, tier_thresholds: TierThresholds | None = None) -> None:
        self.tier_thresholds = tier_thresholds

    def evaluate(
        self,
        ticker: TickerInput,
        indicators: dict[str, Any],
        context: PipelineContext,
    ) -> CandidateResult | None:
        ranked = rank_candidates([{**indicators, "ticker": ticker.ticker}])
        if not ranked:
            return None

        candidate = ranked[0]
        indicator_snapshot = build_indicator_snapshot(candidate.snapshot)
        tier = classify_investability_tier(
            score=candidate.risk_adjusted_score,
            subscores=candidate.subscores,
            risks=candidate.risks,
            snapshot=indicator_snapshot,
            thresholds=self.tier_thresholds,
        )
        return CandidateResult(
            ticker=candidate.ticker,
            name=ticker.name,
            score=candidate.score,
            risk_adjusted_score=candidate.risk_adjusted_score,
            subscores=ScoreBreakdown(**candidate.subscores),
            tier=tier.tier,
            tier_reasons=tier.reasons,
            close=_maybe_float(candidate.snapshot.get("close")),
            lower_bb=_maybe_float(candidate.snapshot.get("bb_lower")),
            rsi14=_maybe_float(candidate.snapshot.get("rsi_14")),
            distance_to_20d_low=_maybe_float(candidate.snapshot.get("distance_to_20d_low")),
            reasons=candidate.reasons,
            risks=candidate.risks,
            indicator_snapshot=indicator_snapshot,
            snapshot_schema_version=INDICATOR_SNAPSHOT_SCHEMA_VERSION,
            generated_at=context.generated_at,
        )


class ScreenPipeline:
    def __init__(
        self,
        settings: Settings,
        universe_provider: UniverseProvider | None = None,
        market_data_provider: MarketDataProvider | None = None,
        indicator_engine: IndicatorEngine | None = None,
        candidate_scorer: CandidateScorer | None = None,
        earnings_calendar_provider: EarningsCalendarProvider | None = None,
        benchmark_market_data_provider: MarketDataProvider | None = None,
    ) -> None:
        self.settings = settings
        self.universe_provider = universe_provider or StaticUniverseProvider()
        self.market_data_provider = market_data_provider or build_market_data_provider(settings)
        self.indicator_engine = indicator_engine or TechnicalIndicatorEngine()
        self.candidate_scorer = candidate_scorer or RankedCandidateScorer()
        self.earnings_calendar_provider = earnings_calendar_provider or build_earnings_calendar_provider(settings)
        self.benchmark_market_data_provider = benchmark_market_data_provider or build_market_data_provider(settings)

    def run(self, context: PipelineContext) -> tuple[ScreenRunResult, RunArtifacts]:
        tickers = self.universe_provider.load_universe(context)
        candidates: list[CandidateResult] = []
        failures: list[str] = []
        notes = list(self.settings.default_notes)

        prepare = getattr(self.market_data_provider, "prepare", None)
        if callable(prepare):
            prepare(tickers, context)

        earnings_by_ticker: dict[str, EarningsInfo] = {}
        if self.earnings_calendar_provider is not None:
            try:
                earnings_by_ticker = self.earnings_calendar_provider.fetch(
                    [item.ticker for item in tickers], context.run_date
                )
            except Exception as exc:  # pragma: no cover
                notes.append(f"Earnings calendar unavailable: {exc}")

        benchmark_context: dict[str, Any] = {}
        if self.benchmark_market_data_provider is not None:
            try:
                benchmark_context = fetch_benchmark_context(self.benchmark_market_data_provider, context)
            except Exception as exc:  # pragma: no cover
                notes.append(f"Benchmark context unavailable: {exc}")

        provider_failures = getattr(self.market_data_provider, "failures", {})
        if isinstance(provider_failures, dict):
            failures.extend(f"{ticker}: {message}" for ticker, message in provider_failures.items())

        bars_nonempty_count = 0
        latest_bar_date_mismatch_count = 0
        insufficient_history_count = 0

        for ticker in tickers:
            if isinstance(provider_failures, dict) and ticker.ticker in provider_failures:
                continue
            try:
                history = self.market_data_provider.fetch_history(ticker, context)
                if history is not None and not history.empty:
                    bars_nonempty_count += 1
                    try:
                        latest_bar = history["date"].max()
                        latest_bar_date = latest_bar.date() if hasattr(latest_bar, "date") else latest_bar
                        if latest_bar_date != context.run_date:
                            latest_bar_date_mismatch_count += 1
                    except Exception:
                        latest_bar_date_mismatch_count += 1
                    if len(history) < 60:
                        insufficient_history_count += 1
                indicators = self.indicator_engine.compute(history, ticker, context)
                indicators = merge_benchmark_context(indicators, benchmark_context)
                indicators = merge_earnings_context(indicators, earnings_by_ticker.get(ticker.ticker))
                candidate = self.candidate_scorer.evaluate(ticker, indicators, context)
                if candidate is not None:
                    candidates.append(candidate)
            except Exception as exc:  # pragma: no cover
                failures.append(f"{ticker.ticker}: {exc}")

        candidates.sort(key=lambda candidate: (-_selection_score(candidate), -candidate.score, candidate.ticker))

        planned_tickers = [item.ticker for item in tickers]

        result = ScreenRunResult(
            metadata=RunMetadata(
                run_date=context.run_date,
                generated_at=context.generated_at,
                universe=context.universe_name,
                run_mode=context.run_mode,
                dry_run=context.dry_run,
                artifact_directory=context.output_dir,
                planned_ticker_count=len(planned_tickers),
                successful_ticker_count=len(planned_tickers) - len(failures),
                failed_ticker_count=len(failures),
                bars_nonempty_count=bars_nonempty_count,
                latest_bar_date_mismatch_count=latest_bar_date_mismatch_count,
                insufficient_history_count=insufficient_history_count,
                planned_tickers=planned_tickers,
                data_failures=failures,
                notes=notes,
            ),
            candidates=candidates,
        )

        artifacts = RunArtifacts()
        if not context.dry_run:
            artifacts = self._write_artifacts(
                result,
                context.output_dir,
                benchmark_context=benchmark_context,
            )
        return result, artifacts

    def _write_artifacts(
        self,
        result: ScreenRunResult,
        output_dir: Path,
        *,
        benchmark_context: dict[str, Any] | None = None,
    ) -> RunArtifacts:
        ensure_directory(output_dir)
        markdown_path = write_text(
            output_dir / self.settings.markdown_report_name,
            build_markdown_report(result),
        )
        json_report_path = write_json(
            output_dir / self.settings.json_report_name,
            build_json_report(result),
        )
        metadata_path = write_json(
            output_dir / self.settings.metadata_report_name,
            result.metadata.model_dump(mode="json"),
        )
        try:
            latest_dir = ensure_directory(output_dir.parent / "latest")
            state_path = output_dir.parent / "alerts" / result.metadata.run_date.isoformat() / "alert-state.json"
            state = load_alert_state(state_path)
            document, next_state = build_daily_alert_document(
                result,
                state=state,
                artifact_directory=str(output_dir),
                report_path=str(json_report_path),
                metadata_path=str(metadata_path),
                benchmark_context=benchmark_context,
            )
            run_alert_path, stable_alert_path = build_daily_alert_paths(output_dir, latest_dir)
            write_alert_document(run_alert_path, stable_alert_path, document)
            save_alert_state(state_path, next_state)
        except Exception as exc:
            result.metadata.notes.append(f"Alert sidecar generation failed: {exc}")
            write_json(metadata_path, result.metadata.model_dump(mode="json"))
            raise AlertSidecarError(str(exc)) from exc
        return RunArtifacts(
            markdown_path=markdown_path,
            json_report_path=json_report_path,
            metadata_path=metadata_path,
            alert_events_path=run_alert_path,
            stable_alert_events_path=stable_alert_path,
        )


def build_context(
    run_date: date,
    generated_at: datetime | None = None,
    dry_run: bool = False,
    output_dir: Path | str = Path("output"),
    run_mode: str = "daily",
    universe_name: str = "NASDAQ-100",
) -> PipelineContext:
    return PipelineContext(
        run_date=run_date,
        generated_at=normalize_generated_at(generated_at),
        dry_run=dry_run,
        output_dir=Path(output_dir),
        run_mode=run_mode,
        universe_name=universe_name,
    )


__all__ = [
    "RankedCandidateScorer",
    "ScreenPipeline",
    "build_context",
]


def _selection_score(candidate: CandidateResult) -> int:
    return candidate.risk_adjusted_score if candidate.risk_adjusted_score is not None else candidate.score

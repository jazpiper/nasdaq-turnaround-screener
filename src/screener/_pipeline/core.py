from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from screener.alerts import AlertSidecarError, build_daily_alert_document
from screener.alerts.policy import evaluate_daily_quality_gate
from screener.alerts.state import load_alert_state, save_alert_state
from screener.alerts.writer import build_daily_alert_paths, write_alert_document
from screener.config import Settings
from screener.data import EarningsCalendarProvider, EarningsInfo
from screener.data.resilience import derive_market_data_reliability_label
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
from screener.reporting.outcomes import build_previous_candidate_outcomes
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
        self.universe_provider = universe_provider or StaticUniverseProvider(
            tickers=settings.universe_tickers,
            overlay_tickers=settings.universe_overlay_tickers,
            overlay_source=settings.universe_overlay_source,
        )
        self.market_data_provider = market_data_provider or build_market_data_provider(settings)
        self.indicator_engine = indicator_engine or TechnicalIndicatorEngine()
        self.candidate_scorer = candidate_scorer or RankedCandidateScorer()
        self.earnings_calendar_provider = earnings_calendar_provider or build_earnings_calendar_provider(settings)
        self.benchmark_market_data_provider = benchmark_market_data_provider or build_market_data_provider(settings)

    def run(self, context: PipelineContext) -> tuple[ScreenRunResult, RunArtifacts]:
        run_started_at = datetime.now(UTC)
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
        provider_status = _safe_provider_status(getattr(self.market_data_provider, "provider_status", []))
        reliability_label = derive_market_data_reliability_label(provider_status)
        if isinstance(provider_failures, dict):
            failures.extend(f"{ticker}: {message}" for ticker, message in provider_failures.items())

        bars_nonempty_count = 0
        latest_bar_date_mismatch_count = 0
        insufficient_history_count = 0
        current_closes: dict[str, float] = {}

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
                    close = _latest_close(history)
                    if close is not None:
                        current_closes[ticker.ticker.upper()] = close
                indicators = self.indicator_engine.compute(history, ticker, context)
                indicators = merge_benchmark_context(indicators, benchmark_context)
                indicators = merge_earnings_context(indicators, earnings_by_ticker.get(ticker.ticker))
                candidate = self.candidate_scorer.evaluate(ticker, indicators, context)
                if candidate is not None:
                    candidates.append(candidate)
            except Exception as exc:  # pragma: no cover
                failures.append(f"{ticker.ticker}: {exc}")

        candidates.sort(key=lambda candidate: (-_selection_score(candidate), -candidate.score, candidate.ticker))
        previous_candidate_outcomes = build_previous_candidate_outcomes(
            current_run_date=context.run_date.isoformat(),
            current_closes=current_closes,
            daily_output_root=context.output_dir.parent,
        )

        planned_tickers = [item.ticker for item in tickers]

        run_completed_at = datetime.now(UTC)
        metadata = RunMetadata(
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
            market_data_provider_status=provider_status,
            reliability_label=reliability_label,
            run_started_at=run_started_at,
            run_completed_at=run_completed_at,
            run_duration_seconds=round((run_completed_at - run_started_at).total_seconds(), 3),
            notes=notes,
        )
        metadata.quality_gate = evaluate_daily_quality_gate(metadata)
        metadata.quality_gate_reasons = _daily_quality_gate_reasons(metadata)
        metadata.observability = _build_run_observability(metadata)

        result = ScreenRunResult(
            metadata=metadata,
            candidates=candidates,
            previous_candidate_outcomes=previous_candidate_outcomes,
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
            latest_dir = output_dir.parent / "latest"
            state_path = output_dir.parent / "alerts" / result.metadata.run_date.isoformat() / "alert-state.json"
            state = load_alert_state(state_path, expected_run_date=result.metadata.run_date.isoformat())
            document, next_state = build_daily_alert_document(
                result,
                state=state,
                artifact_directory=str(output_dir),
                report_path=str(json_report_path),
                metadata_path=str(metadata_path),
                benchmark_context=benchmark_context,
            )
            stable_alert_path = _daily_stable_alert_path(output_dir, latest_dir)
            run_alert_path, _ = build_daily_alert_paths(output_dir, latest_dir)
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


def _safe_provider_status(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    statuses: list[dict[str, object]] = []
    allowed_keys = {
        "provider",
        "role",
        "status",
        "attempted_ticker_count",
        "successful_ticker_count",
        "failed_ticker_count",
        "error_kind",
        "rate_limited",
        "retry_count",
        "used_cache",
        "used_stale_cache",
        "cooldown_active",
        "fallback_provider",
        "message",
    }
    for item in value:
        if isinstance(item, dict):
            statuses.append({str(key): item[key] for key in allowed_keys if key in item})
    return statuses


def _daily_quality_gate_reasons(metadata: RunMetadata) -> list[str]:
    reasons: list[str] = []
    if metadata.failed_ticker_count > 20:
        reasons.append("failed_ticker_count_gt_20")
    elif metadata.failed_ticker_count > 5:
        reasons.append("failed_ticker_count_gt_5")
    if metadata.bars_nonempty_count < 80:
        reasons.append("bars_nonempty_count_lt_80")
    if metadata.latest_bar_date_mismatch_count > 10:
        reasons.append("latest_bar_date_mismatch_count_gt_10")
    elif metadata.latest_bar_date_mismatch_count > 0:
        reasons.append("latest_bar_date_mismatch_count_gt_0")
    if metadata.insufficient_history_count > 5:
        reasons.append("insufficient_history_count_gt_5")
    return reasons


def _build_run_observability(metadata: RunMetadata) -> dict[str, object]:
    return {
        "run_status": metadata.run_status,
        "quality_gate": metadata.quality_gate,
        "quality_gate_reasons": list(metadata.quality_gate_reasons),
        "run_duration_seconds": metadata.run_duration_seconds,
        "failure_counts": {
            "failed_tickers": metadata.failed_ticker_count,
            "latest_bar_date_mismatches": metadata.latest_bar_date_mismatch_count,
            "insufficient_history": metadata.insufficient_history_count,
        },
        "data_coverage": {
            "planned_tickers": metadata.planned_ticker_count,
            "successful_tickers": metadata.successful_ticker_count,
            "bars_nonempty": metadata.bars_nonempty_count,
        },
        "reliability_label": metadata.reliability_label,
    }


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


def _latest_close(history: Any) -> float | None:
    try:
        if history is None or history.empty or "close" not in history:
            return None
        value = history.sort_values("date").iloc[-1]["close"] if "date" in history else history.iloc[-1]["close"]
        return _maybe_float(value)
    except Exception:
        return None


def _daily_stable_alert_path(output_dir: Path, latest_dir: Path) -> Path | None:
    if latest_dir.is_symlink() and latest_dir.resolve(strict=False) != output_dir.resolve(strict=False):
        return None
    ensure_directory(latest_dir)
    return latest_dir / "alert-events.json"

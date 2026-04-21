from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any

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
from screener.scoring import rank_candidates
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
        return CandidateResult(
            ticker=candidate.ticker,
            score=candidate.score,
            subscores=ScoreBreakdown(**candidate.subscores),
            close=_maybe_float(candidate.snapshot.get("close")),
            lower_bb=_maybe_float(candidate.snapshot.get("bb_lower")),
            rsi14=_maybe_float(candidate.snapshot.get("rsi_14")),
            distance_to_20d_low=_maybe_float(candidate.snapshot.get("distance_to_20d_low")),
            reasons=candidate.reasons,
            risks=candidate.risks,
            indicator_snapshot=build_indicator_snapshot(candidate.snapshot),
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

        for ticker in tickers:
            if isinstance(provider_failures, dict) and ticker.ticker in provider_failures:
                continue
            try:
                history = self.market_data_provider.fetch_history(ticker, context)
                indicators = self.indicator_engine.compute(history, ticker, context)
                indicators = merge_benchmark_context(indicators, benchmark_context)
                indicators = merge_earnings_context(indicators, earnings_by_ticker.get(ticker.ticker))
                candidate = self.candidate_scorer.evaluate(ticker, indicators, context)
                if candidate is not None:
                    candidates.append(candidate)
            except Exception as exc:  # pragma: no cover
                failures.append(f"{ticker.ticker}: {exc}")

        candidates.sort(key=lambda candidate: (-candidate.score, candidate.ticker))

        result = ScreenRunResult(
            metadata=RunMetadata(
                run_date=context.run_date,
                generated_at=context.generated_at,
                universe=context.universe_name,
                run_mode=context.run_mode,
                dry_run=context.dry_run,
                artifact_directory=context.output_dir,
                data_failures=failures,
                notes=notes,
            ),
            candidates=candidates,
        )

        artifacts = RunArtifacts()
        if not context.dry_run:
            artifacts = self._write_artifacts(result, context.output_dir)
        return result, artifacts

    def _write_artifacts(self, result: ScreenRunResult, output_dir: Path) -> RunArtifacts:
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
        return RunArtifacts(
            markdown_path=markdown_path,
            json_report_path=json_report_path,
            metadata_path=metadata_path,
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


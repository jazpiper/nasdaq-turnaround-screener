from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import pandas as pd

from screener.config import Settings
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
from screener.storage.files import ensure_directory, write_json, write_text


@runtime_checkable
class UniverseProvider(Protocol):
    def load_universe(self, context: PipelineContext) -> list[TickerInput]:
        """Return normalized ticker definitions for the requested run."""


@runtime_checkable
class MarketDataProvider(Protocol):
    def fetch_history(self, ticker: TickerInput, context: PipelineContext) -> pd.DataFrame:
        """Return normalized OHLCV history for a ticker."""


@runtime_checkable
class IndicatorEngine(Protocol):
    def compute(self, history: pd.DataFrame, ticker: TickerInput, context: PipelineContext) -> dict[str, Any]:
        """Compute indicator values from normalized history."""


@runtime_checkable
class CandidateScorer(Protocol):
    def evaluate(
        self,
        ticker: TickerInput,
        indicators: dict[str, Any],
        context: PipelineContext,
    ) -> CandidateResult | None:
        """Return a scored candidate, or None when the ticker does not qualify."""


class PlaceholderUniverseProvider:
    def load_universe(self, context: PipelineContext) -> list[TickerInput]:
        return [TickerInput(ticker="PLACEHOLDER", name="Placeholder Candidate")]


class PlaceholderMarketDataProvider:
    def fetch_history(self, ticker: TickerInput, context: PipelineContext) -> pd.DataFrame:
        return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])


class PlaceholderIndicatorEngine:
    def compute(self, history: pd.DataFrame, ticker: TickerInput, context: PipelineContext) -> dict[str, Any]:
        return {"status": "placeholder", "rows": int(history.shape[0])}


class PlaceholderCandidateScorer:
    def evaluate(
        self,
        ticker: TickerInput,
        indicators: dict[str, Any],
        context: PipelineContext,
    ) -> CandidateResult | None:
        return None


class ScreenPipeline:
    def __init__(
        self,
        settings: Settings,
        universe_provider: UniverseProvider | None = None,
        market_data_provider: MarketDataProvider | None = None,
        indicator_engine: IndicatorEngine | None = None,
        candidate_scorer: CandidateScorer | None = None,
    ) -> None:
        self.settings = settings
        self.universe_provider = universe_provider or PlaceholderUniverseProvider()
        self.market_data_provider = market_data_provider or PlaceholderMarketDataProvider()
        self.indicator_engine = indicator_engine or PlaceholderIndicatorEngine()
        self.candidate_scorer = candidate_scorer or PlaceholderCandidateScorer()

    def run(self, context: PipelineContext) -> tuple[ScreenRunResult, RunArtifacts]:
        generated_at = context.generated_at
        tickers = self.universe_provider.load_universe(context)
        candidates: list[CandidateResult] = []
        failures: list[str] = []

        for ticker in tickers:
            try:
                history = self.market_data_provider.fetch_history(ticker, context)
                indicators = self.indicator_engine.compute(history, ticker, context)
                candidate = self.candidate_scorer.evaluate(ticker, indicators, context)
                if candidate is not None:
                    candidates.append(candidate)
            except Exception as exc:  # pragma: no cover, defensive scaffold
                failures.append(f"{ticker.ticker}: {exc}")

        if not candidates:
            candidates.append(
                CandidateResult(
                    ticker="PLACEHOLDER",
                    score=0.0,
                    subscores=ScoreBreakdown(),
                    reasons=[
                        "Pipeline scaffold executed successfully.",
                        "Concrete data, indicators, and scoring are pending integration.",
                    ],
                    risks=["No live market analysis is produced in scaffold mode."],
                    generated_at=generated_at,
                )
            )

        result = ScreenRunResult(
            metadata=RunMetadata(
                run_date=context.run_date,
                generated_at=generated_at,
                universe=context.universe_name,
                run_mode=context.run_mode,
                dry_run=context.dry_run,
                artifact_directory=context.output_dir,
                data_failures=failures,
                notes=list(self.settings.default_notes),
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


def build_context(run_date, generated_at: datetime | None = None, dry_run: bool = False, output_dir: Path | str = Path("output"), run_mode: str = "daily", universe_name: str = "NASDAQ-100") -> PipelineContext:
    return PipelineContext(
        run_date=run_date,
        generated_at=generated_at or datetime.now().astimezone(),
        dry_run=dry_run,
        output_dir=Path(output_dir),
        run_mode=run_mode,
        universe_name=universe_name,
    )

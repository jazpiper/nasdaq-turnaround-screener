from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

import pandas as pd

from screener.models import CandidateResult, PipelineContext, TickerInput


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


__all__ = [
    "CandidateScorer",
    "IndicatorEngine",
    "MarketDataProvider",
    "UniverseProvider",
]


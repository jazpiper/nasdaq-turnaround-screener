from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from screener.scoring import TierThresholds

from .grid import TierThresholdsGrid
from .objective import ObjectiveScore, objective

if TYPE_CHECKING:
    from screener.backtest import BacktestObservation


@dataclass(frozen=True)
class GridResult:
    """All scored combinations from a single tuning window, ranked by objective."""

    scores: list[ObjectiveScore]  # sorted: valid first (desc excess_return), then invalid
    horizon: int

    @property
    def best(self) -> ObjectiveScore | None:
        """Highest-scoring valid combination, or None if none passed min_samples."""
        return next((s for s in self.scores if s.is_valid), None)


def tune_single_window(
    observations: list[BacktestObservation],
    horizon: int,
    grid: TierThresholdsGrid | None = None,
    min_samples: int = 5,
) -> GridResult:
    """Evaluate every grid combination against observations and rank by excess return.

    Uses stored subscores/snapshot on each observation so indicator scoring
    is not re-run — only tier classification is repeated per combination.
    """
    if grid is None:
        grid = TierThresholdsGrid()

    scores: list[ObjectiveScore] = [
        objective(observations, thresholds, horizon=horizon, min_samples=min_samples)
        for thresholds in grid
    ]

    scores.sort(key=lambda s: (not s.is_valid, -(s.excess_return or 0.0), s.sample_count))

    return GridResult(scores=scores, horizon=horizon)

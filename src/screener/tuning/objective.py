from __future__ import annotations

from dataclasses import dataclass
from statistics import fmean
from typing import TYPE_CHECKING

from screener.scoring import TierThresholds, classify_investability_tier
from screener.scoring.tiering import BUY_REVIEW_TIER

if TYPE_CHECKING:
    from screener.backtest import BacktestObservation


@dataclass(frozen=True)
class ObjectiveScore:
    """Result of evaluating one TierThresholds combination against observations."""

    thresholds: TierThresholds
    horizon: int
    # None when fewer than min_samples buy-review candidates were found
    excess_return: float | None
    sample_count: int

    @property
    def is_valid(self) -> bool:
        return self.excess_return is not None


def reclassify_tier(observation: BacktestObservation, thresholds: TierThresholds) -> str:
    """Re-classify a stored observation using new tier thresholds.

    Uses the observation's stored subscores and snapshot so indicator scoring
    does not need to be re-run.
    """
    decision = classify_investability_tier(
        score=observation.score,
        subscores=observation.subscores,
        risks=observation.risks,
        snapshot=observation.snapshot,
        thresholds=thresholds,
    )
    return decision.tier


def objective(
    observations: list[BacktestObservation],
    thresholds: TierThresholds,
    horizon: int,
    min_samples: int = 5,
) -> ObjectiveScore:
    """Compute mean excess return for buy-review tier under given thresholds.

    Observations are re-classified without re-running indicator scoring.
    Returns ObjectiveScore with excess_return=None when fewer than
    min_samples pass the buy-review filter.
    """
    excess_returns: list[float] = []
    for obs in observations:
        if reclassify_tier(obs, thresholds) != BUY_REVIEW_TIER:
            continue
        stock = obs.forward_returns.get(horizon)
        benchmark = obs.benchmark_forward_returns.get(horizon)
        if stock is None or benchmark is None:
            continue
        excess_returns.append(stock - benchmark)

    sample_count = len(excess_returns)
    if sample_count < min_samples:
        return ObjectiveScore(
            thresholds=thresholds,
            horizon=horizon,
            excess_return=None,
            sample_count=sample_count,
        )

    return ObjectiveScore(
        thresholds=thresholds,
        horizon=horizon,
        excess_return=round(fmean(excess_returns), 4),
        sample_count=sample_count,
    )

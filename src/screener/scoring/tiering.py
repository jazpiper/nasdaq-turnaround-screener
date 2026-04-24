from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Sequence

BUY_REVIEW_TIER = "buy-review"
WATCHLIST_TIER = "watchlist"
AVOID_HIGH_RISK_TIER = "avoid/high-risk"

BUY_REVIEW_MIN_SCORE = 60
BUY_REVIEW_MIN_REVERSAL = 15
BUY_REVIEW_MIN_VOLUME_RATIO = 0.8
BUY_REVIEW_MAX_RISK_COUNT = 3


@dataclass(frozen=True)
class TierThresholds:
    """Tunable cut-offs for buy-review tier classification.

    Defaults match the hard-coded constants so existing behaviour is unchanged
    when no explicit instance is supplied.
    """

    min_score: int = BUY_REVIEW_MIN_SCORE
    min_reversal: int = BUY_REVIEW_MIN_REVERSAL
    min_volume_ratio: float = BUY_REVIEW_MIN_VOLUME_RATIO
    max_risk_count: int = BUY_REVIEW_MAX_RISK_COUNT


@dataclass(frozen=True)
class TierDecision:
    tier: str
    reasons: list[str]


_DEFAULT_THRESHOLDS = TierThresholds()


def classify_investability_tier(
    *,
    score: int,
    subscores: Mapping[str, int],
    risks: Sequence[str],
    snapshot: Mapping[str, object],
    thresholds: TierThresholds | None = None,
) -> TierDecision:
    """Separate broad turnaround discovery from candidates worth buy review."""
    t = thresholds if thresholds is not None else _DEFAULT_THRESHOLDS
    earnings_penalty = int(snapshot.get("earnings_penalty", 0) or 0)
    volatility_penalty = int(snapshot.get("volatility_penalty", 0) or 0)
    severe_weekly_penalty = int(snapshot.get("severe_weekly_penalty", 0) or 0)
    volume_ratio = _as_float(snapshot.get("volume_ratio_20d"))
    reversal_score = int(subscores.get("reversal", 0) or 0)
    risk_count = len(risks)

    high_risk_reasons: list[str] = []
    if bool(snapshot.get("weekly_trend_severe_damage", False)) or severe_weekly_penalty > 0:
        high_risk_reasons.append("severe weekly trend damage")
    if earnings_penalty >= 8:
        high_risk_reasons.append("earnings event risk is too high")
    if volatility_penalty >= 4:
        high_risk_reasons.append("volatility risk is too high")
    if risk_count >= 6:
        high_risk_reasons.append("too many unresolved risk flags")
    if high_risk_reasons:
        return TierDecision(AVOID_HIGH_RISK_TIER, high_risk_reasons)

    missing_buy_review: list[str] = []
    if score < t.min_score:
        missing_buy_review.append("score below buy-review threshold")
    if reversal_score < t.min_reversal:
        missing_buy_review.append("reversal evidence is not strong enough")
    if volume_ratio is None or volume_ratio < t.min_volume_ratio:
        missing_buy_review.append("volume confirmation is not strong enough")
    if risk_count > t.max_risk_count:
        missing_buy_review.append("risk count is above buy-review limit")

    if missing_buy_review:
        return TierDecision(WATCHLIST_TIER, missing_buy_review)

    return TierDecision(
        BUY_REVIEW_TIER,
        [
            "score, reversal, volume, and risk profile qualify for buy review",
        ],
    )


def _as_float(value: object) -> float | None:
    if value is None:
        return None
    return float(value)

from __future__ import annotations

from screener.scoring import AVOID_HIGH_RISK_TIER, BUY_REVIEW_TIER, WATCHLIST_TIER, TierThresholds, classify_investability_tier


def test_classify_investability_tier_accepts_buy_review_profile() -> None:
    decision = classify_investability_tier(
        score=64,
        subscores={"reversal": 18},
        risks=["중기 추세는 아직 하락 압력일 수 있음"],
        snapshot={
            "volume_ratio_20d": 1.1,
            "earnings_penalty": 0,
            "volatility_penalty": 0,
            "severe_weekly_penalty": 0,
            "weekly_trend_severe_damage": False,
        },
    )

    assert decision.tier == BUY_REVIEW_TIER


def test_classify_investability_tier_keeps_weak_volume_on_watchlist() -> None:
    decision = classify_investability_tier(
        score=64,
        subscores={"reversal": 18},
        risks=[],
        snapshot={"volume_ratio_20d": 0.4},
    )

    assert decision.tier == WATCHLIST_TIER
    assert "volume" in " ".join(decision.reasons)


def test_classify_investability_tier_marks_event_risk_as_high_risk() -> None:
    decision = classify_investability_tier(
        score=72,
        subscores={"reversal": 20},
        risks=[],
        snapshot={"volume_ratio_20d": 1.2, "earnings_penalty": 8},
    )

    assert decision.tier == AVOID_HIGH_RISK_TIER


def test_classify_investability_tier_uses_injected_thresholds() -> None:
    # Score=64 normally qualifies for buy-review, but stricter threshold rejects it
    strict = TierThresholds(min_score=70)
    decision = classify_investability_tier(
        score=64,
        subscores={"reversal": 18},
        risks=["중기 추세는 아직 하락 압력일 수 있음"],
        snapshot={
            "volume_ratio_20d": 1.1,
            "earnings_penalty": 0,
            "volatility_penalty": 0,
            "severe_weekly_penalty": 0,
            "weekly_trend_severe_damage": False,
        },
        thresholds=strict,
    )

    assert decision.tier == WATCHLIST_TIER
    assert "score" in " ".join(decision.reasons)


def test_classify_investability_tier_lenient_thresholds_promote_to_buy_review() -> None:
    # Score=55 normally stays on watchlist, but lenient threshold promotes it
    lenient = TierThresholds(min_score=50, min_reversal=10, min_volume_ratio=0.6)
    decision = classify_investability_tier(
        score=55,
        subscores={"reversal": 12},
        risks=["중기 추세는 아직 하락 압력일 수 있음"],
        snapshot={
            "volume_ratio_20d": 0.7,
            "earnings_penalty": 0,
            "volatility_penalty": 0,
            "severe_weekly_penalty": 0,
            "weekly_trend_severe_damage": False,
        },
        thresholds=lenient,
    )

    assert decision.tier == BUY_REVIEW_TIER


def test_tier_thresholds_defaults_match_module_constants() -> None:
    from screener.scoring.tiering import (
        BUY_REVIEW_MAX_RISK_COUNT,
        BUY_REVIEW_MIN_REVERSAL,
        BUY_REVIEW_MIN_SCORE,
        BUY_REVIEW_MIN_VOLUME_RATIO,
    )

    t = TierThresholds()
    assert t.min_score == BUY_REVIEW_MIN_SCORE
    assert t.min_reversal == BUY_REVIEW_MIN_REVERSAL
    assert t.min_volume_ratio == BUY_REVIEW_MIN_VOLUME_RATIO
    assert t.max_risk_count == BUY_REVIEW_MAX_RISK_COUNT

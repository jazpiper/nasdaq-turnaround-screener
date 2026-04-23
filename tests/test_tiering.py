from __future__ import annotations

from screener.scoring import AVOID_HIGH_RISK_TIER, BUY_REVIEW_TIER, WATCHLIST_TIER, classify_investability_tier


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

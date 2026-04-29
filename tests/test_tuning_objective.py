from __future__ import annotations

from datetime import date

from screener.backtest import BacktestObservation
from screener.scoring import TierThresholds
from screener.tuning.objective import ObjectiveScore, objective, reclassify_tier


def _make_obs(
    score: int = 65,
    tier: str = "buy-review",
    subscores: dict | None = None,
    risks: list[str] | None = None,
    snapshot: dict | None = None,
    forward_return: float = 3.0,
    benchmark_return: float = 1.0,
    horizon: int = 10,
) -> BacktestObservation:
    return BacktestObservation(
        run_date=date(2026, 3, 1),
        ticker="AAPL",
        score=score,
        tier=tier,
        reasons=[],
        risks=risks or [],
        forward_returns={horizon: forward_return},
        benchmark_forward_returns={horizon: benchmark_return},
        subscores=subscores or {"reversal": 18, "oversold": 13, "bottom_context": 14, "volume": 5, "market_context": 7},
        snapshot=snapshot or {
            "volume_ratio_20d": 1.1,
            "earnings_penalty": 0,
            "volatility_penalty": 0,
            "severe_weekly_penalty": 0,
            "weekly_trend_severe_damage": False,
        },
    )


def test_reclassify_tier_returns_buy_review_with_default_thresholds() -> None:
    obs = _make_obs(score=65)
    assert reclassify_tier(obs, TierThresholds()) == "buy-review"


def test_reclassify_tier_demotes_with_strict_score_threshold() -> None:
    obs = _make_obs(score=65)
    assert reclassify_tier(obs, TierThresholds(min_score=70)) == "watchlist"


def test_reclassify_tier_uses_risk_adjusted_score_when_available() -> None:
    obs = _make_obs(score=65)
    obs = BacktestObservation(
        run_date=obs.run_date,
        ticker=obs.ticker,
        score=obs.score,
        risk_adjusted_score=58,
        tier=obs.tier,
        reasons=obs.reasons,
        risks=obs.risks,
        forward_returns=obs.forward_returns,
        benchmark_forward_returns=obs.benchmark_forward_returns,
        subscores=obs.subscores,
        snapshot=obs.snapshot,
    )

    assert reclassify_tier(obs, TierThresholds()) == "watchlist"


def test_reclassify_tier_promotes_with_lenient_thresholds() -> None:
    obs = _make_obs(
        score=55,
        subscores={"reversal": 12, "oversold": 10, "bottom_context": 10, "volume": 5, "market_context": 6},
        snapshot={
            "volume_ratio_20d": 0.7,
            "earnings_penalty": 0,
            "volatility_penalty": 0,
            "severe_weekly_penalty": 0,
            "weekly_trend_severe_damage": False,
        },
    )
    lenient = TierThresholds(min_score=50, min_reversal=10, min_volume_ratio=0.6)
    assert reclassify_tier(obs, lenient) == "buy-review"


def test_objective_computes_excess_return() -> None:
    observations = [_make_obs(forward_return=5.0, benchmark_return=2.0) for _ in range(5)]
    score = objective(observations, TierThresholds(), horizon=10, min_samples=5)
    assert score.is_valid
    assert score.excess_return == 3.0
    assert score.sample_count == 5


def test_objective_returns_none_when_below_min_samples() -> None:
    observations = [_make_obs() for _ in range(4)]
    score = objective(observations, TierThresholds(), horizon=10, min_samples=5)
    assert not score.is_valid
    assert score.excess_return is None
    assert score.sample_count == 4


def test_objective_excludes_observations_reclassified_away_from_buy_review() -> None:
    # With min_score=70 only obs with score>=70 qualify. Our obs has score=65.
    observations = [_make_obs(score=65) for _ in range(10)]
    score = objective(observations, TierThresholds(min_score=70), horizon=10, min_samples=5)
    assert not score.is_valid
    assert score.sample_count == 0


def test_objective_skips_missing_forward_returns() -> None:
    obs_with = _make_obs(forward_return=4.0, benchmark_return=1.0)
    obs_without = BacktestObservation(
        run_date=date(2026, 3, 1),
        ticker="MSFT",
        score=65,
        tier="buy-review",
        reasons=[],
        risks=[],
        forward_returns={},  # no data
        benchmark_forward_returns={},
        subscores={"reversal": 18},
        snapshot={
            "volume_ratio_20d": 1.1,
            "earnings_penalty": 0,
            "volatility_penalty": 0,
            "severe_weekly_penalty": 0,
            "weekly_trend_severe_damage": False,
        },
    )
    observations = [obs_with] * 5 + [obs_without] * 3
    score = objective(observations, TierThresholds(), horizon=10, min_samples=5)
    assert score.is_valid
    assert score.sample_count == 5
    assert score.excess_return == 3.0

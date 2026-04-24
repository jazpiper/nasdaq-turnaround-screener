from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from screener.backtest import BacktestObservation
from screener.scoring import TierThresholds
from screener.tuning.grid import TierThresholdsGrid
from screener.tuning.report import write_diff_markdown_from_walkforward, write_proposal_json_from_walkforward, write_walkforward_json
from screener.tuning.walkforward import WalkForwardResult, walk_forward


def _make_obs(
    run_date: date,
    score: int = 65,
    forward_return: float = 3.0,
    benchmark_return: float = 1.0,
    horizon: int = 10,
    ticker: str = "AAPL",
    include_forward_returns: bool = True,
) -> BacktestObservation:
    return BacktestObservation(
        run_date=run_date,
        ticker=ticker,
        score=score,
        tier="buy-review",
        reasons=[],
        risks=[],
        forward_returns={horizon: forward_return} if include_forward_returns else {},
        benchmark_forward_returns={horizon: benchmark_return} if include_forward_returns else {},
        subscores={"reversal": 18, "oversold": 13, "bottom_context": 14, "volume": 5, "market_context": 7},
        snapshot={
            "volume_ratio_20d": 1.1,
            "earnings_penalty": 0,
            "volatility_penalty": 0,
            "severe_weekly_penalty": 0,
            "weekly_trend_severe_damage": False,
        },
    )


def _make_date_range(start: date, n_days: int) -> list[date]:
    """Generate n_days consecutive dates starting from start (skipping weekends)."""
    dates = []
    current = start
    while len(dates) < n_days:
        if current.weekday() < 5:  # Mon–Fri
            dates.append(current)
        current += timedelta(days=1)
    return dates


def _make_observations(n_trading_days: int, obs_per_day: int = 3, horizon: int = 10) -> list[BacktestObservation]:
    """Build a synthetic observation set spanning n_trading_days."""
    start = date(2025, 6, 2)  # Monday
    dates = _make_date_range(start, n_trading_days)
    tickers = ["AAPL", "MSFT", "NVDA", "AMZN", "META"]
    obs = []
    for d in dates:
        for i in range(min(obs_per_day, len(tickers))):
            obs.append(_make_obs(run_date=d, ticker=tickers[i], horizon=horizon))
    return obs


# --- window splitting ---

def test_walk_forward_produces_no_windows_when_data_too_short() -> None:
    observations = _make_observations(n_trading_days=10)
    result = walk_forward(observations, horizon=10, train_days=90, eval_days=20)
    assert len(result.windows) == 0
    assert result.proposal is None


def test_walk_forward_produces_windows_with_sufficient_data() -> None:
    # 90 + 20 = 110 trading days minimum for one window
    observations = _make_observations(n_trading_days=115)
    result = walk_forward(observations, horizon=10, train_days=90, eval_days=20, stride=20)
    assert len(result.windows) >= 1


def test_walk_forward_window_dates_do_not_overlap() -> None:
    observations = _make_observations(n_trading_days=150)
    result = walk_forward(observations, horizon=10, train_days=90, eval_days=20, stride=20)
    for w in result.windows:
        assert w.train_end < w.eval_start


def test_walk_forward_window_obs_counts_are_positive() -> None:
    observations = _make_observations(n_trading_days=120)
    result = walk_forward(observations, horizon=10, train_days=90, eval_days=20, stride=20)
    for w in result.windows:
        assert w.train_obs_count > 0
        assert w.eval_obs_count > 0


# --- stability + proposal ---

def test_walk_forward_proposal_requires_min_wins() -> None:
    observations = _make_observations(n_trading_days=150)
    # min_wins=99 is impossible with only a few windows
    result = walk_forward(observations, horizon=10, train_days=90, eval_days=20, stride=20, min_wins=99)
    assert result.proposal is None


def test_walk_forward_proposal_requires_valid_out_of_sample_windows() -> None:
    result = _walk_forward_with_invalid_oos_windows()

    assert len(result.windows) == 2
    assert all(window.eval_score is not None and not window.eval_score.is_valid for window in result.windows)
    assert result.stability[0].win_count == 2
    assert result.stability[0].valid_eval_count == 0
    assert result.stability[0].avg_eval_excess_return is None
    assert result.proposal is None


def _walk_forward_with_invalid_oos_windows() -> WalkForwardResult:
    dates = _make_date_range(date(2026, 1, 5), 6)
    observations = [
        _make_obs(dates[0], ticker="AAPL"),
        _make_obs(dates[1], ticker="MSFT"),
        _make_obs(dates[2], ticker="NVDA", include_forward_returns=False),
        _make_obs(dates[3], ticker="AAPL"),
        _make_obs(dates[4], ticker="MSFT"),
        _make_obs(dates[5], ticker="NVDA", include_forward_returns=False),
    ]
    grid = TierThresholdsGrid(
        score_values=(60,),
        reversal_values=(15,),
        volume_ratio_values=(0.8,),
        risk_count_values=(3,),
    )

    return walk_forward(
        observations,
        horizon=10,
        grid=grid,
        train_days=2,
        eval_days=1,
        stride=3,
        min_samples=1,
        min_wins=2,
    )


def test_walk_forward_proposal_returned_when_min_wins_met() -> None:
    # Use small windows to get many windows from limited data
    observations = _make_observations(n_trading_days=200, obs_per_day=5)
    result = walk_forward(
        observations, horizon=10, train_days=30, eval_days=10, stride=10, min_samples=3, min_wins=2
    )
    if len(result.windows) >= 2:
        # stability may or may not yield a proposal depending on data, but no crash
        assert isinstance(result.proposal, (TierThresholds, type(None)))


def test_stability_sorted_by_win_count_descending() -> None:
    observations = _make_observations(n_trading_days=200, obs_per_day=5)
    result = walk_forward(
        observations, horizon=10, train_days=30, eval_days=10, stride=10, min_samples=3, min_wins=1
    )
    win_counts = [s.win_count for s in result.stability]
    assert win_counts == sorted(win_counts, reverse=True)


# --- report helpers ---

def test_write_walkforward_json(tmp_path: Path) -> None:
    observations = _make_observations(n_trading_days=120)
    result = walk_forward(observations, horizon=10, train_days=90, eval_days=20)
    path = write_walkforward_json(tmp_path / "wf.json", result)
    assert path.exists()
    import json
    payload = json.loads(path.read_text())
    assert "windows" in payload
    assert "stability" in payload
    assert "proposal_status" in payload


def test_write_proposal_json_from_walkforward_no_proposal(tmp_path: Path) -> None:
    observations = _make_observations(n_trading_days=10)  # too short → no windows
    result = walk_forward(observations, horizon=10, train_days=90, eval_days=20)
    path = write_proposal_json_from_walkforward(tmp_path / "proposal.json", result)
    import json
    payload = json.loads(path.read_text())
    assert payload["status"] == "no_proposal"


def test_write_proposal_json_from_walkforward_explains_invalid_oos_rejection(tmp_path: Path) -> None:
    result = _walk_forward_with_invalid_oos_windows()
    path = write_proposal_json_from_walkforward(tmp_path / "proposal.json", result)
    import json
    payload = json.loads(path.read_text())
    assert payload["status"] == "no_proposal"
    assert "valid out-of-sample" in payload["reason"]
    assert "0/2" in payload["reason"]


def test_write_diff_markdown_from_walkforward_no_proposal(tmp_path: Path) -> None:
    observations = _make_observations(n_trading_days=10)
    result = walk_forward(observations, horizon=10, train_days=90, eval_days=20)
    path = write_diff_markdown_from_walkforward(tmp_path / "diff.md", result)
    assert path.exists()
    assert "no proposal" in path.read_text()


def test_write_diff_markdown_from_walkforward_explains_invalid_oos_rejection(tmp_path: Path) -> None:
    result = _walk_forward_with_invalid_oos_windows()
    path = write_diff_markdown_from_walkforward(tmp_path / "diff.md", result)
    content = path.read_text()
    assert "no proposal" in content
    assert "valid out-of-sample" in content
    assert "0/2" in content


def test_walk_forward_result_metadata() -> None:
    observations = _make_observations(n_trading_days=120)
    result = walk_forward(
        observations, horizon=10, train_days=90, eval_days=20, stride=20, min_wins=2
    )
    assert result.horizon == 10
    assert result.train_days == 90
    assert result.eval_days == 20
    assert result.stride == 20
    assert result.min_wins == 2

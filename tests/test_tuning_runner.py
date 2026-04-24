from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from screener.backtest import BacktestObservation
from screener.scoring import TierThresholds
from screener.tuning.grid import TierThresholdsGrid
from screener.tuning.report import write_diff_markdown, write_grid_csv, write_proposal_json
from screener.tuning.runner import GridResult, tune_single_window


def _make_obs(
    score: int = 65,
    forward_return: float = 3.0,
    benchmark_return: float = 1.0,
    horizon: int = 10,
) -> BacktestObservation:
    return BacktestObservation(
        run_date=date(2026, 3, 1),
        ticker="AAPL",
        score=score,
        tier="buy-review",
        reasons=[],
        risks=[],
        forward_returns={horizon: forward_return},
        benchmark_forward_returns={horizon: benchmark_return},
        subscores={"reversal": 18, "oversold": 13, "bottom_context": 14, "volume": 5, "market_context": 7},
        snapshot={
            "volume_ratio_20d": 1.1,
            "earnings_penalty": 0,
            "volatility_penalty": 0,
            "severe_weekly_penalty": 0,
            "weekly_trend_severe_damage": False,
        },
    )


def test_tune_single_window_returns_grid_result() -> None:
    observations = [_make_obs() for _ in range(10)]
    result = tune_single_window(observations, horizon=10, min_samples=5)
    assert isinstance(result, GridResult)
    assert result.horizon == 10
    assert len(result.scores) == 400  # default grid


def test_tune_single_window_best_is_none_when_no_obs_qualify() -> None:
    # Score too low to qualify for buy-review under any default grid combination
    observations = [_make_obs(score=10) for _ in range(10)]
    result = tune_single_window(observations, horizon=10, min_samples=5)
    assert result.best is None


def test_tune_single_window_best_has_highest_excess_return() -> None:
    observations = [_make_obs(forward_return=5.0, benchmark_return=1.0) for _ in range(10)]
    result = tune_single_window(observations, horizon=10, min_samples=5)
    best = result.best
    assert best is not None
    # valid scores are sorted desc by excess_return
    valid = [s for s in result.scores if s.is_valid]
    assert valid[0] is best


def test_tune_single_window_custom_grid() -> None:
    observations = [_make_obs() for _ in range(10)]
    tiny_grid = TierThresholdsGrid(
        score_values=(60,),
        reversal_values=(15,),
        volume_ratio_values=(0.8,),
        risk_count_values=(3,),
    )
    result = tune_single_window(observations, horizon=10, grid=tiny_grid, min_samples=5)
    assert len(result.scores) == 1


def test_write_grid_csv_creates_file(tmp_path: Path) -> None:
    observations = [_make_obs() for _ in range(10)]
    result = tune_single_window(observations, horizon=10)
    path = write_grid_csv(tmp_path / "grid.csv", result)
    assert path.exists()
    content = path.read_text()
    assert "min_score" in content
    assert "excess_return" in content


def test_write_proposal_json_creates_file_with_proposal(tmp_path: Path) -> None:
    observations = [_make_obs() for _ in range(10)]
    result = tune_single_window(observations, horizon=10, min_samples=5)
    path = write_proposal_json(tmp_path / "proposal.json", result)
    assert path.exists()
    import json
    payload = json.loads(path.read_text())
    assert payload["status"] in ("proposal", "no_proposal")
    assert "current" in payload


def test_write_proposal_json_no_proposal_when_no_valid_scores(tmp_path: Path) -> None:
    observations = [_make_obs(score=5) for _ in range(10)]
    result = tune_single_window(observations, horizon=10, min_samples=5)
    path = write_proposal_json(tmp_path / "proposal.json", result)
    import json
    payload = json.loads(path.read_text())
    assert payload["status"] == "no_proposal"


def test_write_diff_markdown_creates_file(tmp_path: Path) -> None:
    observations = [_make_obs() for _ in range(10)]
    result = tune_single_window(observations, horizon=10, min_samples=5)
    path = write_diff_markdown(tmp_path / "diff.md", result)
    assert path.exists()
    content = path.read_text()
    assert "Tuning Proposal Diff" in content

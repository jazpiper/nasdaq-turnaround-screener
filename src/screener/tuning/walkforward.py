from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from statistics import fmean
from typing import TYPE_CHECKING

from screener.scoring import TierThresholds

from .grid import TierThresholdsGrid
from .objective import ObjectiveScore, objective
from .runner import tune_single_window

if TYPE_CHECKING:
    from screener.backtest import BacktestObservation

DEFAULT_TRAIN_DAYS = 90
DEFAULT_EVAL_DAYS = 20
DEFAULT_STRIDE = 20
DEFAULT_MIN_WINS = 2


@dataclass(frozen=True)
class WindowResult:
    window_index: int
    train_start: date
    train_end: date
    eval_start: date
    eval_end: date
    train_obs_count: int
    eval_obs_count: int
    best_thresholds: TierThresholds | None
    best_train_score: ObjectiveScore | None
    # out-of-sample evaluation of the train-best thresholds
    eval_score: ObjectiveScore | None


@dataclass(frozen=True)
class ThresholdsStability:
    thresholds: TierThresholds
    win_count: int
    window_indices: list[int]
    valid_eval_count: int
    avg_eval_excess_return: float | None


@dataclass(frozen=True)
class WalkForwardResult:
    windows: list[WindowResult]
    # sorted: most wins first, ties broken by avg_eval_excess_return desc
    stability: list[ThresholdsStability]
    proposal: TierThresholds | None  # None if no combo won >= min_wins windows
    horizon: int
    train_days: int
    eval_days: int
    stride: int
    min_wins: int


def walk_forward(
    observations: list[BacktestObservation],
    horizon: int,
    grid: TierThresholdsGrid | None = None,
    train_days: int = DEFAULT_TRAIN_DAYS,
    eval_days: int = DEFAULT_EVAL_DAYS,
    stride: int = DEFAULT_STRIDE,
    min_samples: int = 5,
    min_wins: int = DEFAULT_MIN_WINS,
) -> WalkForwardResult:
    """Sliding-window grid search with out-of-sample evaluation.

    For each window:
    1. Find best threshold on train observations (in-sample).
    2. Evaluate that threshold on eval observations (out-of-sample).
    3. Track which threshold wins most often across windows.

    Final proposal requires winning >= min_wins windows to guard against
    single-window over-fit.
    """
    if grid is None:
        grid = TierThresholdsGrid()

    unique_dates = sorted({obs.run_date for obs in observations})
    window_results: list[WindowResult] = []

    window_index = 0
    start_pos = 0
    while True:
        train_end_pos = start_pos + train_days
        eval_end_pos = train_end_pos + eval_days

        if eval_end_pos > len(unique_dates):
            break

        train_dates = set(unique_dates[start_pos:train_end_pos])
        eval_dates = set(unique_dates[train_end_pos:eval_end_pos])

        train_obs = [obs for obs in observations if obs.run_date in train_dates]
        eval_obs = [obs for obs in observations if obs.run_date in eval_dates]

        train_result = tune_single_window(train_obs, horizon=horizon, grid=grid, min_samples=min_samples)
        best_train = train_result.best

        eval_score: ObjectiveScore | None = None
        if best_train is not None:
            eval_score = objective(eval_obs, best_train.thresholds, horizon=horizon, min_samples=1)

        window_results.append(
            WindowResult(
                window_index=window_index,
                train_start=unique_dates[start_pos],
                train_end=unique_dates[train_end_pos - 1],
                eval_start=unique_dates[train_end_pos],
                eval_end=unique_dates[eval_end_pos - 1],
                train_obs_count=len(train_obs),
                eval_obs_count=len(eval_obs),
                best_thresholds=best_train.thresholds if best_train else None,
                best_train_score=best_train,
                eval_score=eval_score,
            )
        )

        window_index += 1
        start_pos += stride

    stability = _compute_stability(window_results)
    proposal = _select_proposal(stability, min_wins=min_wins)

    return WalkForwardResult(
        windows=window_results,
        stability=stability,
        proposal=proposal,
        horizon=horizon,
        train_days=train_days,
        eval_days=eval_days,
        stride=stride,
        min_wins=min_wins,
    )


def _compute_stability(windows: list[WindowResult]) -> list[ThresholdsStability]:
    wins: dict[TierThresholds, list[int]] = {}
    eval_returns: dict[TierThresholds, list[float]] = {}

    for w in windows:
        if w.best_thresholds is None:
            continue
        t = w.best_thresholds
        wins.setdefault(t, []).append(w.window_index)
        if w.eval_score is not None and w.eval_score.excess_return is not None:
            eval_returns.setdefault(t, []).append(w.eval_score.excess_return)

    stability: list[ThresholdsStability] = []
    for t, win_indices in wins.items():
        avg = round(fmean(eval_returns[t]), 4) if eval_returns.get(t) else None
        stability.append(
            ThresholdsStability(
                thresholds=t,
                win_count=len(win_indices),
                window_indices=win_indices,
                valid_eval_count=len(eval_returns.get(t, [])),
                avg_eval_excess_return=avg,
            )
        )

    stability.sort(
        key=lambda s: (
            -s.win_count,
            -s.valid_eval_count,
            -(s.avg_eval_excess_return if s.avg_eval_excess_return is not None else float("-inf")),
        )
    )
    return stability


def _select_proposal(stability: list[ThresholdsStability], min_wins: int) -> TierThresholds | None:
    for entry in stability:
        if entry.win_count >= min_wins and entry.valid_eval_count >= min_wins:
            return entry.thresholds
    return None

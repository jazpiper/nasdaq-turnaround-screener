from __future__ import annotations

from screener.scoring import TierThresholds
from screener.tuning.grid import (
    RISK_COUNT_VALUES,
    REVERSAL_VALUES,
    SCORE_VALUES,
    VOLUME_RATIO_VALUES,
    TierThresholdsGrid,
)


def test_default_grid_length() -> None:
    grid = TierThresholdsGrid()
    expected = len(SCORE_VALUES) * len(REVERSAL_VALUES) * len(VOLUME_RATIO_VALUES) * len(RISK_COUNT_VALUES)
    assert len(grid) == expected
    assert expected == 400


def test_default_grid_yields_tier_thresholds() -> None:
    grid = TierThresholdsGrid()
    items = list(grid)
    assert len(items) == 400
    assert all(isinstance(t, TierThresholds) for t in items)


def test_default_grid_contains_current_defaults() -> None:
    defaults = TierThresholds()
    grid = TierThresholdsGrid()
    assert defaults in list(grid)


def test_custom_grid_length() -> None:
    grid = TierThresholdsGrid(
        score_values=(55, 60),
        reversal_values=(15,),
        volume_ratio_values=(0.8, 1.0),
        risk_count_values=(3,),
    )
    assert len(grid) == 4


def test_custom_grid_yields_expected_combinations() -> None:
    grid = TierThresholdsGrid(
        score_values=(55,),
        reversal_values=(15,),
        volume_ratio_values=(0.8,),
        risk_count_values=(3,),
    )
    items = list(grid)
    assert items == [TierThresholds(min_score=55, min_reversal=15, min_volume_ratio=0.8, max_risk_count=3)]

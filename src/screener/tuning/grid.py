from __future__ import annotations

from itertools import product
from typing import Iterator

from screener.scoring import TierThresholds

# Default search space for tier cut-off tuning (v1: tier-level parameters only).
# Expand to score-construction constants in v2.
SCORE_VALUES: tuple[int, ...] = (50, 55, 60, 65, 70)
REVERSAL_VALUES: tuple[int, ...] = (10, 12, 15, 18, 20)
VOLUME_RATIO_VALUES: tuple[float, ...] = (0.6, 0.8, 1.0, 1.2)
RISK_COUNT_VALUES: tuple[int, ...] = (2, 3, 4, 5)


class TierThresholdsGrid:
    """Cartesian product of tier threshold candidates.

    Default search space yields 400 combinations (5×5×4×4).
    Pass custom sequences to restrict or extend the grid.
    """

    def __init__(
        self,
        score_values: tuple[int, ...] = SCORE_VALUES,
        reversal_values: tuple[int, ...] = REVERSAL_VALUES,
        volume_ratio_values: tuple[float, ...] = VOLUME_RATIO_VALUES,
        risk_count_values: tuple[int, ...] = RISK_COUNT_VALUES,
    ) -> None:
        self._score_values = score_values
        self._reversal_values = reversal_values
        self._volume_ratio_values = volume_ratio_values
        self._risk_count_values = risk_count_values

    def __iter__(self) -> Iterator[TierThresholds]:
        for score, reversal, volume_ratio, risk_count in product(
            self._score_values,
            self._reversal_values,
            self._volume_ratio_values,
            self._risk_count_values,
        ):
            yield TierThresholds(
                min_score=score,
                min_reversal=reversal,
                min_volume_ratio=volume_ratio,
                max_risk_count=risk_count,
            )

    def __len__(self) -> int:
        return (
            len(self._score_values)
            * len(self._reversal_values)
            * len(self._volume_ratio_values)
            * len(self._risk_count_values)
        )

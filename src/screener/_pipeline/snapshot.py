from __future__ import annotations

from typing import Any

INDICATOR_SNAPSHOT_SCHEMA_VERSION = 2
INDICATOR_SNAPSHOT_KEYS: tuple[str, ...] = (
    "close",
    "low",
    "bb_lower",
    "rsi_14",
    "sma_5",
    "sma_20",
    "sma_60",
    "atr_14",
    "atr_14_pct",
    "daily_range_pct",
    "bb_width_pct",
    "close_above_open",
    "close_location_value",
    "lower_wick_ratio",
    "upper_wick_ratio",
    "real_body_pct",
    "gap_down_pct",
    "gap_down_reclaim",
    "inside_day",
    "bullish_engulfing_like",
    "distance_to_20d_low",
    "distance_to_60d_low",
    "average_volume_20d",
    "volume_ratio_20d",
    "close_improvement_streak",
    "rsi_3d_change",
    "market_context_score",
    "qqq_return_20d",
    "qqq_return_60d",
    "stock_return_20d",
    "stock_return_60d",
    "rel_strength_20d_vs_qqq",
    "rel_strength_60d_vs_qqq",
    "relative_strength_score",
    "earnings_data_available",
    "next_earnings_date",
    "days_to_next_earnings",
    "days_since_last_earnings",
    "earnings_penalty",
    "volatility_penalty",
    "weekly_bars_available",
    "weekly_close",
    "weekly_sma_5",
    "weekly_sma_10",
    "weekly_close_improving",
    "weekly_trend_penalty",
    "weekly_trend_severe_damage",
)


def build_indicator_snapshot(indicators: dict[str, Any]) -> dict[str, Any]:
    snapshot: dict[str, Any] = {"schema_version": INDICATOR_SNAPSHOT_SCHEMA_VERSION}
    for key in INDICATOR_SNAPSHOT_KEYS:
        if key not in indicators:
            continue
        value = _snapshot_value(indicators[key])
        if value is not None:
            snapshot[key] = value
    return snapshot


def _maybe_float(value: Any) -> float | None:
    return None if value is None else float(value)


def _snapshot_value(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "item") and callable(value.item):
        value = value.item()
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        return float(value)
    if isinstance(value, str):
        return value
    return str(value)


__all__ = [
    "INDICATOR_SNAPSHOT_KEYS",
    "INDICATOR_SNAPSHOT_SCHEMA_VERSION",
    "build_indicator_snapshot",
]


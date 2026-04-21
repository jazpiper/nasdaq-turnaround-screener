from __future__ import annotations

from datetime import date, timedelta

import pytest

from screener.data.market_data import DailyBar
from screener.indicators.technicals import add_indicator_columns


def test_add_indicator_columns_computes_atr_and_volatility_fields() -> None:
    start = date(2026, 1, 1)
    bars = [
        DailyBar(
            ticker="AAPL",
            trading_date=start + timedelta(days=index),
            open=100.0,
            high=102.0,
            low=98.0,
            close=100.0,
            adj_close=100.0,
            volume=1_500_000.0,
        )
        for index in range(20)
    ]

    latest = add_indicator_columns(bars)[-1]

    assert latest["atr_14"] == 4.0
    assert latest["atr_14_pct"] == 4.0
    assert latest["daily_range_pct"] == 4.0
    assert latest["bb_width_pct"] == 0.0


def test_add_indicator_columns_computes_candle_structure_fields() -> None:
    start = date(2026, 1, 1)
    bars = [
        DailyBar(
            ticker="AAPL",
            trading_date=start + timedelta(days=index),
            open=100.0,
            high=102.0,
            low=98.0,
            close=100.0,
            adj_close=100.0,
            volume=1_500_000.0,
        )
        for index in range(18)
    ]
    bars.append(
        DailyBar(
            ticker="AAPL",
            trading_date=start + timedelta(days=18),
            open=100.0,
            high=101.0,
            low=96.0,
            close=97.0,
            adj_close=97.0,
            volume=1_500_000.0,
        )
    )
    bars.append(
        DailyBar(
            ticker="AAPL",
            trading_date=start + timedelta(days=19),
            open=97.0,
            high=101.0,
            low=97.0,
            close=100.0,
            adj_close=100.0,
            volume=1_500_000.0,
        )
    )

    latest = add_indicator_columns(bars)[-1]

    assert latest["close_above_open"] is True
    assert latest["close_location_value"] == pytest.approx(0.75)
    assert latest["lower_wick_ratio"] == pytest.approx(0.0)
    assert latest["upper_wick_ratio"] == pytest.approx(0.25)
    assert latest["real_body_pct"] == pytest.approx(0.75)
    assert latest["gap_down_pct"] == pytest.approx(0.0)
    assert latest["gap_down_reclaim"] is False
    assert latest["inside_day"] is True
    assert latest["bullish_engulfing_like"] is True

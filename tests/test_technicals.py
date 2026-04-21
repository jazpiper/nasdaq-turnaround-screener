from __future__ import annotations

from datetime import date, timedelta

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

from __future__ import annotations

from datetime import date, timedelta

from screener.data import DailyBar
from screener.overlay.hot_sector import HOT_SECTOR_BASKETS, SECTOR_PROXY_TICKERS, build_hot_sector_overlay, write_hot_sector_overlay


def make_bars(ticker: str, *, start_close: float, daily_step: float, days: int = 90) -> list[DailyBar]:
    start = date(2026, 1, 1)
    bars: list[DailyBar] = []
    close = start_close
    for index in range(days):
        close = start_close + (daily_step * index)
        current_date = start + timedelta(days=index)
        bars.append(
            DailyBar(
                ticker=ticker,
                trading_date=current_date,
                open=close - 0.2,
                high=close + 0.4,
                low=close - 0.6,
                close=close,
                adj_close=close,
                volume=1_000_000.0 + index,
            )
        )
    return bars


class StubFetcher:
    def __init__(self, bars_by_ticker: dict[str, list[DailyBar]]) -> None:
        self.bars_by_ticker = bars_by_ticker

    def fetch(self, tickers):
        requested = tuple(tickers)
        return type(
            "FetchResult",
            (),
            {
                "bars_by_ticker": {ticker: self.bars_by_ticker[ticker] for ticker in requested if ticker in self.bars_by_ticker},
                "failed_tickers": {},
                "source_statuses": [],
            },
        )()


def test_build_hot_sector_overlay_prefers_strongest_sector_groups(tmp_path):
    bars_by_ticker: dict[str, list[DailyBar]] = {
        "QQQ": make_bars("QQQ", start_close=500.0, daily_step=1.0),
        "XLK": make_bars("XLK", start_close=300.0, daily_step=2.0),
        "XLC": make_bars("XLC", start_close=250.0, daily_step=1.8),
        "XLI": make_bars("XLI", start_close=200.0, daily_step=1.5),
        "XLB": make_bars("XLB", start_close=180.0, daily_step=0.4),
        "XLU": make_bars("XLU", start_close=160.0, daily_step=0.2),
        "XLY": make_bars("XLY", start_close=190.0, daily_step=0.3),
        "XLV": make_bars("XLV", start_close=210.0, daily_step=0.1),
        "XLF": make_bars("XLF", start_close=170.0, daily_step=0.0),
        "XLE": make_bars("XLE", start_close=150.0, daily_step=-0.1),
        "XLP": make_bars("XLP", start_close=140.0, daily_step=-0.2),
        "XLRE": make_bars("XLRE", start_close=130.0, daily_step=-0.3),
        "SMH": make_bars("SMH", start_close=220.0, daily_step=0.4),
    }

    for sector in ("technology", "communication_services", "industrials", "materials", "utilities", "consumer_discretionary", "health_care", "financials", "energy", "consumer_staples", "real_estate", "semiconductors"):
        for ticker in HOT_SECTOR_BASKETS[sector]:
            if ticker not in bars_by_ticker:
                bars_by_ticker[ticker] = make_bars(ticker, start_close=100.0, daily_step=0.05)

    result = build_hot_sector_overlay(fetcher=StubFetcher(bars_by_ticker), max_sectors=3, per_sector_cap=2)
    payload_path = write_hot_sector_overlay(tmp_path / "hot-sector-overlay.json", result)

    assert payload_path.exists()
    assert len(result.selected_sectors) == 3
    assert set(result.selected_sectors) == {"technology", "communication_services", "industrials"}
    assert len(result.selected_tickers) == 6
    assert len(set(result.selected_tickers)) == 6
    assert all(
        any(ticker in HOT_SECTOR_BASKETS[sector] for sector in result.selected_sectors)
        for ticker in result.selected_tickers
    )
    assert all(signal.selected is True for signal in result.signals)

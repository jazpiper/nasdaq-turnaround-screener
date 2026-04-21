from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from screener.config import get_settings
from screener.data.market_data import (
    MarketDataProviderError,
    TwelveDataDailyBarFetcher,
    YFinanceDailyBarFetcher,
    build_market_data_fetcher,
    normalize_ohlcv_rows,
)


class MarketDataProviderTests(unittest.TestCase):
    def test_normalize_ohlcv_rows_accepts_twelve_data_shape(self):
        bars = normalize_ohlcv_rows(
            "MSFT",
            [
                {
                    "datetime": "2026-04-20",
                    "open": "100.5",
                    "high": "110.0",
                    "low": "99.5",
                    "close": "108.25",
                    "volume": "123456",
                },
                {
                    "datetime": "2026-04-21",
                    "open": "108.5",
                    "high": "112.0",
                    "low": "107.5",
                    "close": "111.25",
                    "volume": "222222",
                },
            ],
        )

        self.assertEqual(len(bars), 2)
        self.assertEqual(bars[0].trading_date.isoformat(), "2026-04-20")
        self.assertEqual(bars[0].adj_close, bars[0].close)
        self.assertEqual(bars[-1].close, 111.25)

    def test_build_market_data_fetcher_defaults_to_yfinance(self):
        fetcher = build_market_data_fetcher()
        self.assertIsInstance(fetcher, YFinanceDailyBarFetcher)

    def test_build_market_data_fetcher_supports_twelve_data_aliases(self):
        for provider_name in ("twelve-data", "twelvedata", "twelve_data"):
            fetcher = build_market_data_fetcher(provider_name, twelve_data_api_key="secret")
            self.assertIsInstance(fetcher, TwelveDataDailyBarFetcher)

    def test_build_market_data_fetcher_rejects_unknown_provider(self):
        with self.assertRaises(MarketDataProviderError):
            build_market_data_fetcher("mystery")

    def test_twelve_data_fetcher_requires_api_key(self):
        fetcher = TwelveDataDailyBarFetcher(api_key=None)
        with self.assertRaises(MarketDataProviderError):
            fetcher.fetch(["AAPL"])

    def test_twelve_data_fetcher_normalizes_mocked_response(self):
        payload = json.dumps(
            {
                "meta": {"symbol": "AAPL", "interval": "1day"},
                "values": [
                    {
                        "datetime": "2026-04-21",
                        "open": "189.0",
                        "high": "193.0",
                        "low": "188.0",
                        "close": "192.5",
                        "volume": "1000",
                    },
                    {
                        "datetime": "2026-04-20",
                        "open": "187.0",
                        "high": "190.0",
                        "low": "186.5",
                        "close": "188.5",
                        "volume": "900",
                    },
                ],
            }
        )
        requested_urls: list[str] = []

        def reader(url: str) -> str:
            requested_urls.append(url)
            return payload

        fetcher = TwelveDataDailyBarFetcher(api_key="secret", response_reader=reader)
        result = fetcher.fetch(["aapl"])

        self.assertIn("symbol=AAPL", requested_urls[0])
        self.assertEqual(result.failed_tickers, {})
        self.assertEqual(list(result.bars_by_ticker), ["AAPL"])
        self.assertEqual(result.bars_by_ticker["AAPL"][0].trading_date.isoformat(), "2026-04-20")
        self.assertEqual(result.bars_by_ticker["AAPL"][-1].close, 192.5)

    def test_twelve_data_fetcher_collects_provider_errors_per_ticker(self):
        def reader(url: str) -> str:
            if "symbol=BAD" in url:
                return json.dumps({"status": "error", "message": "bad symbol"})
            return json.dumps(
                {
                    "values": [
                        {
                            "datetime": "2026-04-21",
                            "open": "10",
                            "high": "11",
                            "low": "9",
                            "close": "10.5",
                            "volume": "100",
                        }
                    ]
                }
            )

        fetcher = TwelveDataDailyBarFetcher(api_key="secret", response_reader=reader)
        result = fetcher.fetch(["GOOD", "BAD"])

        self.assertIn("GOOD", result.bars_by_ticker)
        self.assertEqual(result.failed_tickers["BAD"], "bad symbol")

    def test_get_settings_reads_provider_configuration_from_env(self):
        self.addCleanup(lambda: __import__("os").environ.pop("SCREENER_MARKET_DATA_PROVIDER", None))
        self.addCleanup(lambda: __import__("os").environ.pop("TWELVE_DATA_API_KEY", None))
        __import__("os").environ["SCREENER_MARKET_DATA_PROVIDER"] = "twelve-data"
        __import__("os").environ["TWELVE_DATA_API_KEY"] = "env-secret"

        settings = get_settings()

        self.assertEqual(settings.market_data_provider, "twelve-data")
        self.assertEqual(settings.twelve_data_api_key, "env-secret")


if __name__ == "__main__":
    unittest.main()

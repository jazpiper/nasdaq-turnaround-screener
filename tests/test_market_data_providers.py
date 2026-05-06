from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from urllib.error import HTTPError
from unittest import mock

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from screener.config import get_settings
from screener.data.market_data import (
    DEFAULT_HTTP_TIMEOUT_SECONDS,
    FetchResult,
    MarketDataProviderError,
    ResilientMarketDataFetcher,
    TwelveDataDailyBarFetcher,
    YFinanceDailyBarFetcher,
    _read_url,
    build_market_data_fetcher,
    normalize_ohlcv_rows,
)
from screener.data.resilience import MarketDataRateLimitError, ProviderResilienceState
from screener.secrets import load_openclaw_secrets


class MarketDataProviderTests(unittest.TestCase):
    def setUp(self):
        self._env_backup = os.environ.copy()
        for key in (
            "SCREENER_MARKET_DATA_PROVIDER",
            "TWELVE_DATA_API_KEY",
            "TWELVE_DATA_BASE_URL",
            "SCREENER_OPENCLAW_SECRETS_PATH",
        ):
            os.environ.pop(key, None)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._env_backup)

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

    def test_twelve_data_fetcher_allows_default_and_public_https_base_urls(self):
        default_fetcher = TwelveDataDailyBarFetcher(api_key="secret")
        self.assertEqual(default_fetcher.base_url, "https://api.twelvedata.com/time_series")

        custom_fetcher = TwelveDataDailyBarFetcher(
            api_key="secret",
            base_url="https://data.example.com/time_series",
        )
        self.assertEqual(custom_fetcher.base_url, "https://data.example.com/time_series")

    def test_twelve_data_fetcher_rejects_unsafe_base_urls(self):
        unsafe_urls = [
            "file:///tmp/time_series",
            "https:///time_series",
            "https://user:pass@api.twelvedata.com/time_series",
            "https://localhost/time_series",
            "https://127.0.0.1/time_series",
            "https://10.0.0.5/time_series",
            "https://172.16.0.5/time_series",
            "https://192.168.1.10/time_series",
            "https://169.254.10.20/time_series",
            "https://[::1]/time_series",
        ]

        for base_url in unsafe_urls:
            with self.subTest(base_url=base_url):
                with self.assertRaises(MarketDataProviderError):
                    TwelveDataDailyBarFetcher(api_key="secret", base_url=base_url)

    def test_build_market_data_fetcher_rejects_unsafe_twelve_data_base_url(self):
        with self.assertRaises(MarketDataProviderError):
            build_market_data_fetcher(
                "twelve-data",
                twelve_data_api_key="secret",
                twelve_data_base_url="https://127.0.0.1/time_series",
            )

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

    def test_read_url_uses_default_timeout(self):
        observed: dict[str, object] = {}

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self) -> bytes:
                return b'{"ok": true}'

        def fake_urlopen(request, timeout=None):
            observed["url"] = request.full_url
            observed["timeout"] = timeout
            return FakeResponse()

        with mock.patch("screener.data.market_data.urlopen", side_effect=fake_urlopen):
            body = _read_url("https://example.com/test")

        self.assertEqual(body, '{"ok": true}')
        self.assertEqual(observed["url"], "https://example.com/test")
        self.assertEqual(observed["timeout"], DEFAULT_HTTP_TIMEOUT_SECONDS)

    def test_read_url_classifies_http_429_without_leaking_url(self):
        def fake_urlopen(request, timeout=None):
            raise HTTPError(
                request.full_url,
                429,
                "Too Many Requests api_key=secret-value",
                {"Retry-After": "2"},
                None,
            )

        with mock.patch("screener.data.market_data.urlopen", side_effect=fake_urlopen):
            with self.assertRaises(MarketDataRateLimitError) as raised:
                _read_url("https://example.com/time_series?apikey=secret-value")

        self.assertEqual(raised.exception.retry_after_seconds, 2.0)
        self.assertNotIn("secret-value", str(raised.exception))
        self.assertNotIn("example.com", str(raised.exception))

    def test_twelve_data_retries_rate_limit_and_records_status(self):
        responses = [
            json.dumps({"status": "error", "message": "429 too many requests api_key=secret-value"}),
            _twelve_data_success_payload(),
        ]
        sleeps: list[float] = []

        def reader(url: str) -> str:
            return responses.pop(0)

        fetcher = TwelveDataDailyBarFetcher(
            api_key="secret",
            response_reader=reader,
            max_retries=1,
            initial_backoff_seconds=0.5,
            max_backoff_seconds=2.0,
            sleeper=sleeps.append,
            resilience_state=ProviderResilienceState(),
        )
        result = fetcher.fetch(["AAPL"])

        self.assertEqual(result.failed_tickers, {})
        self.assertIn("AAPL", result.bars_by_ticker)
        self.assertEqual(sleeps, [0.5])
        self.assertEqual(result.source_statuses[0]["provider"], "twelve-data")
        self.assertEqual(result.source_statuses[0]["retry_count"], 1)
        self.assertEqual(result.source_statuses[0]["status"], "ok")

    def test_twelve_data_cooldown_short_circuits_after_rate_limit(self):
        calls = 0

        def reader(url: str) -> str:
            nonlocal calls
            calls += 1
            return json.dumps({"status": "error", "message": "429 current limit being exceeded"})

        state = ProviderResilienceState()
        fetcher = TwelveDataDailyBarFetcher(
            api_key="secret",
            response_reader=reader,
            max_retries=0,
            cooldown_seconds=30.0,
            sleeper=lambda seconds: None,
            resilience_state=state,
        )

        first = fetcher.fetch(["AAPL"])
        second = fetcher.fetch(["MSFT"])

        self.assertEqual(calls, 1)
        self.assertEqual(first.source_statuses[0]["status"], "rate_limited")
        self.assertEqual(second.source_statuses[0]["cooldown_active"], True)
        self.assertEqual(second.failed_tickers["MSFT"], "rate_limited: provider cooldown active")

    def test_resilient_fetcher_falls_back_failed_tickers_and_keeps_statuses(self):
        class FakeFetcher:
            def __init__(self, name, result):
                self.provider_name = name
                self.result = result
                self.calls: list[tuple[str, ...]] = []

            def fetch(self, tickers):
                self.calls.append(tuple(tickers))
                return self.result

        good_bar = normalize_ohlcv_rows("GOOD", [_ohlcv_row()])
        bad_bar = normalize_ohlcv_rows("BAD", [_ohlcv_row(close="22")])
        primary = FakeFetcher(
            "primary-source",
            FetchResult(
                bars_by_ticker={"GOOD": good_bar},
                failed_tickers={"BAD": "429 too many requests token=secret-value"},
                source_statuses=[
                    {
                        "provider": "primary-source",
                        "status": "partial_success",
                        "attempted_ticker_count": 2,
                        "successful_ticker_count": 1,
                        "failed_ticker_count": 1,
                        "error_kind": "rate_limited",
                        "rate_limited": True,
                        "message": "429 too many requests token=secret-value",
                    }
                ],
            ),
        )
        fallback = FakeFetcher(
            "fallback-source",
            FetchResult(
                bars_by_ticker={"BAD": bad_bar},
                failed_tickers={},
                source_statuses=[
                    {
                        "provider": "fallback-source",
                        "status": "ok",
                        "attempted_ticker_count": 1,
                        "successful_ticker_count": 1,
                        "failed_ticker_count": 0,
                    }
                ],
            ),
        )

        result = ResilientMarketDataFetcher([("primary-source", primary), ("fallback-source", fallback)]).fetch(
            ["GOOD", "BAD"]
        )

        self.assertEqual(primary.calls, [("GOOD", "BAD")])
        self.assertEqual(fallback.calls, [("BAD",)])
        self.assertEqual(result.failed_tickers, {})
        self.assertEqual(set(result.bars_by_ticker), {"GOOD", "BAD"})
        self.assertEqual(result.source_statuses[0]["fallback_provider"], "fallback-source")
        self.assertEqual(result.source_statuses[1]["role"], "fallback")
        self.assertNotIn("secret-value", json.dumps(result.source_statuses))

    def test_build_market_data_fetcher_accepts_fallback_chain(self):
        fetcher = build_market_data_fetcher("twelve-data,yfinance", twelve_data_api_key="secret")

        self.assertIsInstance(fetcher, ResilientMarketDataFetcher)
        self.assertEqual([name for name, _ in fetcher.providers], ["twelve-data", "yfinance"])

    def test_yfinance_fetcher_handles_single_ticker_multiindex_columns(self):
        index = pd.Index([pd.Timestamp("2026-04-20"), pd.Timestamp("2026-04-21")], name="Date")
        columns = pd.MultiIndex.from_tuples(
            [
                ("QQQ", "Open"),
                ("QQQ", "High"),
                ("QQQ", "Low"),
                ("QQQ", "Close"),
                ("QQQ", "Adj Close"),
                ("QQQ", "Volume"),
            ],
            names=["Ticker", "Price"],
        )
        frame = pd.DataFrame(
            [
                [500.0, 505.0, 498.0, 504.0, 504.0, 10_000_000],
                [504.0, 507.0, 503.0, 506.0, 506.0, 11_000_000],
            ],
            index=index,
            columns=columns,
        )

        class FakeYFinance:
            @staticmethod
            def download(**kwargs):
                return frame

        original_module = sys.modules.get("yfinance")
        sys.modules["yfinance"] = FakeYFinance()
        try:
            fetcher = YFinanceDailyBarFetcher()
            result = fetcher.fetch(["QQQ"])
        finally:
            if original_module is None:
                sys.modules.pop("yfinance", None)
            else:
                sys.modules["yfinance"] = original_module

        self.assertEqual(result.failed_tickers, {})
        self.assertEqual(len(result.bars_by_ticker["QQQ"]), 2)
        self.assertEqual(result.bars_by_ticker["QQQ"][-1].close, 506.0)

    def test_load_openclaw_secrets_reads_nested_values(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            secrets_path = Path(tmp_dir) / "secrets.json"
            secrets_path.write_text(json.dumps({"twelveData": {"apiKey": "oc-secret"}}), encoding="utf-8")

            secrets = load_openclaw_secrets(secrets_path)

        self.assertIsNotNone(secrets)
        self.assertEqual(secrets.get("/twelveData/apiKey"), "oc-secret")
        self.assertIsNone(secrets.get("/missing"))

    def test_get_settings_reads_provider_configuration_from_env(self):
        os.environ["SCREENER_MARKET_DATA_PROVIDER"] = "twelve-data"
        os.environ["TWELVE_DATA_API_KEY"] = "env-secret"

        settings = get_settings()

        self.assertEqual(settings.market_data_provider, "twelve-data")
        self.assertEqual(settings.twelve_data_api_key, "env-secret")

    def test_get_settings_reads_openclaw_secrets_without_auto_switching_provider(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            secrets_path = Path(tmp_dir) / "secrets.json"
            secrets_path.write_text(json.dumps({"twelveData": {"apiKey": "secret-from-openclaw"}}), encoding="utf-8")

            settings = get_settings(openclaw_secrets_path=secrets_path)

        self.assertEqual(settings.market_data_provider, "yfinance")
        self.assertEqual(settings.twelve_data_api_key, "secret-from-openclaw")
        self.assertEqual(settings.openclaw_secrets_path, secrets_path)

    def test_get_settings_prefers_explicit_env_over_openclaw_secrets(self):
        os.environ["TWELVE_DATA_API_KEY"] = "env-secret"
        with tempfile.TemporaryDirectory() as tmp_dir:
            secrets_path = Path(tmp_dir) / "secrets.json"
            secrets_path.write_text(json.dumps({"twelveData": {"apiKey": "secret-from-openclaw"}}), encoding="utf-8")

            settings = get_settings(openclaw_secrets_path=secrets_path)

        self.assertEqual(settings.market_data_provider, "yfinance")
        self.assertEqual(settings.twelve_data_api_key, "env-secret")

    def test_get_settings_falls_back_to_yfinance_when_no_twelve_data_key_exists(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            secrets_path = Path(tmp_dir) / "missing-secrets.json"
            settings = get_settings(openclaw_secrets_path=secrets_path)

        self.assertEqual(settings.market_data_provider, "yfinance")
        self.assertIsNone(settings.twelve_data_api_key)


def _ohlcv_row(*, close: str = "10.5") -> dict[str, str]:
    return {
        "datetime": "2026-04-21",
        "open": "10",
        "high": "11",
        "low": "9",
        "close": close,
        "volume": "100",
    }


def _twelve_data_success_payload() -> str:
    return json.dumps({"values": [_ohlcv_row()]})


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from math import ceil
from pathlib import Path
from time import sleep as _sleep
from typing import Callable, Protocol

DAILY_CREDIT_EXHAUSTED_MARKERS = (
    "run out of api credits for the day",
    "current limit being 800",
)

from screener.config import Settings
from screener.data import DailyBar, TwelveDataDailyBarFetcher
from screener.storage.files import ensure_directory, write_json
from screener.universe.nasdaq100 import NASDAQ_100_TICKERS

DEFAULT_COLLECTION_WINDOWS = 6
DEFAULT_MAX_CREDITS_PER_MINUTE = 8
DEFAULT_INTRADAY_INTERVAL = "1min"
DEFAULT_INTRADAY_OUTPUT_SIZE = 1


class IntradayFetcher(Protocol):
    def fetch(self, tickers: list[str]) -> object:
        """Fetch market data for one or more tickers."""


@dataclass(frozen=True)
class CollectionPlan:
    window_index: int
    total_windows: int
    window_tickers: list[str]
    minute_batches: list[list[str]]
    remaining_tickers: list[str]
    max_credits_per_minute: int


@dataclass(frozen=True)
class CollectedQuote:
    ticker: str
    timestamp: str
    open: float
    high: float
    low: float
    close: float
    volume: float

    @classmethod
    def from_bar(cls, bar: DailyBar) -> "CollectedQuote":
        return cls(
            ticker=bar.ticker,
            timestamp=bar.trading_date.isoformat(),
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
            volume=bar.volume,
        )


@dataclass(frozen=True)
class CollectionArtifacts:
    run_directory: Path | None
    metadata_path: Path | None
    quotes_path: Path | None


@dataclass(frozen=True)
class CollectionResult:
    plan: CollectionPlan
    collected: list[CollectedQuote]
    successes: list[str]
    failures: dict[str, str]
    artifacts: CollectionArtifacts


class TwelveDataWindowCollector:
    def __init__(
        self,
        settings: Settings,
        *,
        fetcher: IntradayFetcher | None = None,
        sleeper: Callable[[float], None] | None = None,
        clock: Callable[[], datetime] | None = None,
        universe: list[str] | None = None,
        interval: str = DEFAULT_INTRADAY_INTERVAL,
        outputsize: int = DEFAULT_INTRADAY_OUTPUT_SIZE,
    ) -> None:
        self.settings = settings
        self.fetcher = fetcher or TwelveDataDailyBarFetcher(
            api_key=settings.twelve_data_api_key,
            base_url=settings.twelve_data_base_url,
            interval=interval,
            outputsize=outputsize,
        )
        self.sleeper = sleeper or _sleep
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.universe = list(universe or NASDAQ_100_TICKERS)

    def build_plan(
        self,
        *,
        window_index: int,
        total_windows: int = DEFAULT_COLLECTION_WINDOWS,
        max_credits_per_minute: int = DEFAULT_MAX_CREDITS_PER_MINUTE,
    ) -> CollectionPlan:
        if total_windows <= 0:
            raise ValueError("total_windows must be positive")
        if not 0 <= window_index < total_windows:
            raise ValueError("window_index must be within total_windows")
        if max_credits_per_minute <= 0:
            raise ValueError("max_credits_per_minute must be positive")

        windows = _split_evenly(self.universe, total_windows)
        window_tickers = windows[window_index]
        remaining = [ticker for later in windows[window_index + 1 :] for ticker in later]
        minute_batches = _chunk(window_tickers, max_credits_per_minute)
        return CollectionPlan(
            window_index=window_index,
            total_windows=total_windows,
            window_tickers=window_tickers,
            minute_batches=minute_batches,
            remaining_tickers=remaining,
            max_credits_per_minute=max_credits_per_minute,
        )

    def run_window(
        self,
        *,
        run_date: date,
        output_root: Path,
        window_index: int,
        total_windows: int = DEFAULT_COLLECTION_WINDOWS,
        max_credits_per_minute: int = DEFAULT_MAX_CREDITS_PER_MINUTE,
        dry_run: bool = False,
    ) -> CollectionResult:
        plan = self.build_plan(
            window_index=window_index,
            total_windows=total_windows,
            max_credits_per_minute=max_credits_per_minute,
        )
        started_at = self.clock()
        collected: list[CollectedQuote] = []
        failures: dict[str, str] = {}
        pause_seconds = ceil(60 / max_credits_per_minute)

        should_stop_early = False
        for batch_index, batch in enumerate(plan.minute_batches):
            for ticker_index, ticker in enumerate(batch):
                result = self.fetcher.fetch([ticker])
                bars_by_ticker = getattr(result, "bars_by_ticker", {})
                failed_tickers = getattr(result, "failed_tickers", {})
                if ticker in failed_tickers:
                    failure_message = str(failed_tickers[ticker])
                    failures[ticker] = failure_message
                    should_stop_early = _is_daily_credit_exhausted(failure_message)
                else:
                    bars = bars_by_ticker.get(ticker) or []
                    if not bars:
                        failures[ticker] = "No price rows returned"
                    else:
                        collected.append(CollectedQuote.from_bar(bars[-1]))

                if should_stop_early:
                    for later_index, later_batch in enumerate(plan.minute_batches[batch_index:], start=batch_index):
                        start_at = ticker_index + 1 if later_index == batch_index else 0
                        for pending in later_batch[start_at:]:
                            failures[pending] = failure_message
                    break

                is_last_request = batch_index == len(plan.minute_batches) - 1 and ticker_index == len(batch) - 1
                if not is_last_request:
                    self.sleeper(pause_seconds)
            if should_stop_early:
                break

        completed_at = self.clock()
        successes = [quote.ticker for quote in collected]
        artifacts = CollectionArtifacts(run_directory=None, metadata_path=None, quotes_path=None)
        if not dry_run:
            artifacts = self._write_artifacts(
                output_root=output_root,
                run_date=run_date,
                started_at=started_at,
                completed_at=completed_at,
                result=CollectionResult(
                    plan=plan,
                    collected=collected,
                    successes=successes,
                    failures=failures,
                    artifacts=artifacts,
                ),
            )
        return CollectionResult(
            plan=plan,
            collected=collected,
            successes=successes,
            failures=failures,
            artifacts=artifacts,
        )

    def _write_artifacts(
        self,
        *,
        output_root: Path,
        run_date: date,
        started_at: datetime,
        completed_at: datetime,
        result: CollectionResult,
    ) -> CollectionArtifacts:
        run_directory = ensure_directory(
            output_root
            / run_date.isoformat()
            / f"window-{result.plan.window_index + 1:02d}-of-{result.plan.total_windows:02d}"
            / started_at.strftime("run-%Y%m%dT%H%M%SZ")
        )
        metadata_path = write_json(
            run_directory / "collection-metadata.json",
            {
                "run_date": run_date.isoformat(),
                "started_at": started_at.isoformat(),
                "completed_at": completed_at.isoformat(),
                "provider": "twelve-data",
                "interval": DEFAULT_INTRADAY_INTERVAL,
                "window_index": result.plan.window_index,
                "window_number": result.plan.window_index + 1,
                "total_windows": result.plan.total_windows,
                "max_credits_per_minute": result.plan.max_credits_per_minute,
                "planned_tickers": result.plan.window_tickers,
                "minute_batches": result.plan.minute_batches,
                "successes": result.successes,
                "failures": result.failures,
                "remaining_tickers": result.plan.remaining_tickers,
                "uncollected_tickers": [
                    ticker for ticker in result.plan.window_tickers if ticker not in result.successes
                ],
                "collected_count": len(result.collected),
                "failed_count": len(result.failures),
                "remaining_count": len(result.plan.remaining_tickers),
            },
        )
        quotes_path = write_json(
            run_directory / "collected-quotes.json",
            {
                "quotes": [quote.__dict__ for quote in result.collected],
            },
        )
        return CollectionArtifacts(
            run_directory=run_directory,
            metadata_path=metadata_path,
            quotes_path=quotes_path,
        )


def _split_evenly(items: list[str], parts: int) -> list[list[str]]:
    base = len(items) // parts
    remainder = len(items) % parts
    windows: list[list[str]] = []
    start = 0
    for index in range(parts):
        size = base + (1 if index < remainder else 0)
        windows.append(items[start : start + size])
        start += size
    return windows


def _chunk(items: list[str], size: int) -> list[list[str]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


def _is_daily_credit_exhausted(message: str) -> bool:
    normalized = message.strip().lower()
    return any(marker in normalized for marker in DAILY_CREDIT_EXHAUSTED_MARKERS)

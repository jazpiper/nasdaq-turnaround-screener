from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from math import isfinite
from pathlib import Path
from typing import Any

from screener.data import DailyBar


@dataclass(frozen=True)
class StagedIntradayQuote:
    ticker: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    source_path: Path

    def as_daily_bar(self, *, volume: float | None = None) -> DailyBar:
        trading_day = self.timestamp.date()
        return DailyBar(
            ticker=self.ticker,
            trading_date=trading_day,
            open=self.open,
            high=self.high,
            low=self.low,
            close=self.close,
            adj_close=self.close,
            volume=self.volume if volume is None else volume,
        )


@dataclass(frozen=True)
class StagedIntradaySnapshot:
    run_directory: Path
    metadata_path: Path
    quotes_path: Path
    completed_at: datetime
    quotes_by_ticker: dict[str, StagedIntradayQuote]


def discover_latest_intraday_snapshot(output_root: Path, run_date: date) -> StagedIntradaySnapshot | None:
    date_root = Path(output_root) / run_date.isoformat()
    candidates: list[tuple[datetime, Path, Path, Path]] = []
    if not date_root.exists():
        return None

    for metadata_path in date_root.glob("window-*/run-*/collection-metadata.json"):
        run_directory = metadata_path.parent
        quotes_path = run_directory / "collected-quotes.json"
        if not quotes_path.exists():
            continue
        try:
            metadata = _read_json(metadata_path)
        except (OSError, ValueError, TypeError):
            continue
        if not isinstance(metadata, dict):
            continue
        completed_at_text = metadata.get("completed_at") or metadata.get("started_at")
        if not completed_at_text:
            continue
        try:
            completed_at = _parse_timestamp(str(completed_at_text))
        except ValueError:
            continue
        if completed_at.date() != run_date:
            continue
        candidates.append((completed_at, run_directory, metadata_path, quotes_path))

    if not candidates:
        return None

    for completed_at, run_directory, metadata_path, quotes_path in sorted(candidates, key=lambda item: item[0], reverse=True):
        try:
            quotes_payload = _read_json(quotes_path)
        except (OSError, ValueError, TypeError):
            continue
        if not isinstance(quotes_payload, dict):
            continue
        quotes_by_ticker: dict[str, StagedIntradayQuote] = {}
        quote_payloads = quotes_payload.get("quotes", [])
        if not isinstance(quote_payloads, list):
            continue
        for quote_payload in quote_payloads:
            staged_quote = _parse_staged_quote(quote_payload, run_date=run_date, source_path=quotes_path)
            if staged_quote is not None:
                quotes_by_ticker[staged_quote.ticker] = staged_quote
        if not quotes_by_ticker:
            continue

        return StagedIntradaySnapshot(
            run_directory=run_directory,
            metadata_path=metadata_path,
            quotes_path=quotes_path,
            completed_at=completed_at,
            quotes_by_ticker=quotes_by_ticker,
        )
    return None


def merge_history_with_staged_quote(history: list[DailyBar], staged_quote: StagedIntradayQuote | None) -> list[DailyBar]:
    if not history or staged_quote is None:
        return list(history)

    merged = list(history)
    neutral_volume = _neutral_staged_volume(merged)
    staged_bar = staged_quote.as_daily_bar(volume=neutral_volume)
    last_bar = merged[-1]
    if staged_bar.trading_date < last_bar.trading_date:
        return merged
    if staged_bar.trading_date == last_bar.trading_date:
        merged[-1] = DailyBar(
            ticker=last_bar.ticker,
            trading_date=last_bar.trading_date,
            open=last_bar.open,
            high=max(last_bar.high, staged_bar.high),
            low=min(last_bar.low, staged_bar.low),
            close=staged_bar.close,
            adj_close=staged_bar.close,
            volume=last_bar.volume,
        )
        return merged
    merged.append(staged_bar)
    return merged


def _neutral_staged_volume(history: list[DailyBar]) -> float:
    recent = history[-19:] if len(history) >= 19 else history
    if not recent:
        return 0.0
    return sum(bar.volume for bar in recent) / len(recent)


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _parse_staged_quote(payload: Any, *, run_date: date, source_path: Path) -> StagedIntradayQuote | None:
    if not isinstance(payload, dict):
        return None
    try:
        ticker = str(payload["ticker"]).upper()
        timestamp = _parse_timestamp(str(payload["timestamp"]))
        open_price = float(payload["open"])
        high = float(payload["high"])
        low = float(payload["low"])
        close = float(payload["close"])
        volume = float(payload["volume"])
    except (KeyError, TypeError, ValueError):
        return None
    if not ticker or timestamp.date() != run_date:
        return None
    prices = (open_price, high, low, close)
    if not all(isfinite(value) for value in (*prices, volume)):
        return None
    if any(value <= 0 for value in prices) or volume < 0:
        return None
    if high < max(open_price, low, close) or low > min(open_price, high, close):
        return None
    return StagedIntradayQuote(
        ticker=ticker,
        timestamp=timestamp,
        open=open_price,
        high=high,
        low=low,
        close=close,
        volume=volume,
        source_path=source_path,
    )

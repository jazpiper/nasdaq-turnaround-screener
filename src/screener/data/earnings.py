from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Iterable, Protocol


@dataclass(frozen=True)
class EarningsInfo:
    next_earnings_date: date | None = None
    last_earnings_date: date | None = None
    days_to_next_earnings: int | None = None
    days_since_last_earnings: int | None = None


class EarningsCalendarProviderError(RuntimeError):
    """Raised when earnings calendar data cannot be loaded from a configured source."""


class EarningsCalendarProvider(Protocol):
    def fetch(self, tickers: Iterable[str], run_date: date) -> dict[str, EarningsInfo]:
        """Fetch earnings context for the requested tickers."""


class FileBackedEarningsCalendarProvider:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def fetch(self, tickers: Iterable[str], run_date: date) -> dict[str, EarningsInfo]:
        if not self.path.exists():
            raise EarningsCalendarProviderError(f"Configured earnings calendar file does not exist: {self.path}")

        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise EarningsCalendarProviderError(f"Invalid earnings calendar JSON: {self.path}") from exc

        if not isinstance(payload, dict):
            raise EarningsCalendarProviderError("Earnings calendar JSON must be an object keyed by ticker")

        normalized: dict[str, EarningsInfo] = {}
        requested = {ticker.strip().upper() for ticker in tickers if ticker and ticker.strip()}
        for ticker in requested:
            raw_entry = payload.get(ticker)
            if not isinstance(raw_entry, dict):
                continue
            normalized[ticker] = _parse_earnings_info(raw_entry, run_date)
        return normalized


def _parse_earnings_info(payload: dict[str, object], run_date: date) -> EarningsInfo:
    next_earnings_date = _parse_optional_date(payload.get("next_earnings_date"))
    last_earnings_date = _parse_optional_date(payload.get("last_earnings_date"))

    days_to_next = _parse_optional_int(payload.get("days_to_next_earnings"))
    if days_to_next is None and next_earnings_date is not None:
        days_to_next = (next_earnings_date - run_date).days

    days_since_last = _parse_optional_int(payload.get("days_since_last_earnings"))
    if days_since_last is None and last_earnings_date is not None:
        days_since_last = (run_date - last_earnings_date).days

    return EarningsInfo(
        next_earnings_date=next_earnings_date,
        last_earnings_date=last_earnings_date,
        days_to_next_earnings=days_to_next,
        days_since_last_earnings=days_since_last,
    )


def _parse_optional_date(value: object) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    return date.fromisoformat(str(value))


def _parse_optional_int(value: object) -> int | None:
    if value in (None, ""):
        return None
    return int(value)

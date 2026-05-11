from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .nasdaq100 import NASDAQ_100_TICKERS

DEFAULT_UNIVERSE_NAME = "NASDAQ-100"
USER_WATCHLIST_UNIVERSE_NAME = "user-watchlist"


@dataclass(frozen=True)
class UniverseDefinition:
    name: str
    tickers: tuple[str, ...]

    def as_list(self) -> list[str]:
        return list(self.tickers)


def normalize_ticker(ticker: str) -> str:
    normalized = ticker.strip().upper()
    if not normalized:
        raise ValueError("Ticker cannot be blank")
    return normalized.replace(".", "-")


def parse_ticker_list(value: str) -> tuple[str, ...]:
    tickers: list[str] = []
    seen: set[str] = set()
    for part in value.split(","):
        try:
            ticker = normalize_ticker(part)
        except ValueError:
            continue
        if ticker in seen:
            continue
        tickers.append(ticker)
        seen.add(ticker)
    if not tickers:
        raise ValueError("At least one ticker is required")
    return tuple(tickers)


def load_static_universe(
    tickers: Iterable[str] | None = None,
    *,
    name: str = DEFAULT_UNIVERSE_NAME,
    deduplicate: bool = True,
) -> UniverseDefinition:
    source = NASDAQ_100_TICKERS if tickers is None else tickers
    normalized: list[str] = []
    seen: set[str] = set()
    for ticker in source:
        value = normalize_ticker(ticker)
        if deduplicate and value in seen:
            continue
        normalized.append(value)
        seen.add(value)
    return UniverseDefinition(name=name, tickers=tuple(normalized))


def load_ticker_source_file(path: str | Path, *, deduplicate: bool = True) -> tuple[str, ...]:
    source_path = Path(path).expanduser()
    text = source_path.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError(f"Ticker source file is empty: {source_path}")

    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return parse_ticker_list(text.replace("\n", ","))

    if isinstance(payload, dict):
        if "tickers" not in payload:
            raise ValueError(f"Ticker source JSON must include a 'tickers' key: {source_path}")
        payload = payload["tickers"]

    if isinstance(payload, str):
        return parse_ticker_list(payload)

    if not isinstance(payload, list):
        raise ValueError(f"Ticker source JSON must be a list or object with tickers: {source_path}")

    normalized: list[str] = []
    seen: set[str] = set()
    for item in payload:
        ticker_value: str | None
        if isinstance(item, str):
            ticker_value = item
        elif isinstance(item, dict):
            raw_ticker = item.get("ticker")
            ticker_value = None if raw_ticker is None else str(raw_ticker)
        else:
            continue

        try:
            ticker = normalize_ticker(ticker_value)
        except ValueError:
            continue

        if deduplicate and ticker in seen:
            continue
        normalized.append(ticker)
        seen.add(ticker)

    if not normalized:
        raise ValueError(f"No tickers found in source file: {source_path}")
    return tuple(normalized)

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .nasdaq100 import NASDAQ_100_TICKERS

DEFAULT_UNIVERSE_NAME = "NASDAQ-100"


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

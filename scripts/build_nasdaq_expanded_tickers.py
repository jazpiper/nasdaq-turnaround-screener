#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from urllib.request import urlopen

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "config" / "nasdaq-expanded-500.txt"
DEFAULT_LIMIT = 500
EXCLUDED_NAME_FRAGMENTS = (
    "warrant",
    "warrants",
    "unit",
    "units",
    "right",
    "rights",
    "preferred",
    "preference",
    "depositary share",
    "depositary shares",
    "note due",
    "notes due",
    "senior note",
    "senior notes",
    "subordinated note",
    "subordinated notes",
)


def normalize_symbol(symbol: str) -> str:
    return symbol.strip().upper().replace(".", "-")


def is_common_stockish_row(row: dict[str, str]) -> bool:
    symbol = normalize_symbol(row.get("Symbol", ""))
    if not symbol:
        return False
    if any(character in symbol for character in ("^", "$")):
        return False
    if row.get("Test Issue", "").strip().upper() != "N":
        return False
    if row.get("ETF", "").strip().upper() != "N":
        return False
    name = row.get("Security Name", "").strip().lower()
    return not any(fragment in name for fragment in EXCLUDED_NAME_FRAGMENTS)


def parse_nasdaq_listed_text(text: str) -> list[dict[str, str]]:
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return []
    header = lines[0].split("|")
    rows: list[dict[str, str]] = []
    for line in lines[1:]:
        if line.startswith("File Creation Time"):
            continue
        values = line.split("|")
        if len(values) != len(header):
            continue
        rows.append(dict(zip(header, values, strict=True)))
    return rows


def build_nasdaq_expanded_tickers(text: str, *, limit: int = DEFAULT_LIMIT) -> tuple[str, ...]:
    if limit < 1:
        raise ValueError("limit must be at least 1")
    tickers: list[str] = []
    seen: set[str] = set()
    for row in parse_nasdaq_listed_text(text):
        if not is_common_stockish_row(row):
            continue
        ticker = normalize_symbol(row["Symbol"])
        if ticker in seen:
            continue
        tickers.append(ticker)
        seen.add(ticker)
        if len(tickers) >= limit:
            break
    if not tickers:
        raise ValueError("no eligible NASDAQ tickers found in source text")
    return tuple(tickers)


def fetch_source_text(source_url: str, *, timeout_seconds: int = 30) -> str:
    with urlopen(source_url, timeout=timeout_seconds) as response:  # noqa: S310 - configured public NASDAQ source URL
        return response.read().decode("utf-8", errors="replace")


def write_ticker_file(path: Path, tickers: tuple[str, ...]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(tickers) + "\n", encoding="utf-8")
    return path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a NASDAQ-listed common-stock-ish ticker file for expanded daily discovery.",
    )
    parser.add_argument("--source-url", default=DEFAULT_SOURCE_URL, help="Source URL for nasdaqlisted.txt")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH, help="Output ticker file path")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="Maximum ticker count to write")
    parser.add_argument("--timeout", type=int, default=30, help="HTTP timeout seconds")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        source_text = fetch_source_text(args.source_url, timeout_seconds=max(args.timeout, 1))
        tickers = build_nasdaq_expanded_tickers(source_text, limit=args.limit)
        output_path = write_ticker_file(args.output, tickers)
    except (OSError, ValueError) as exc:
        print(f"Ticker file build failed: {exc}", file=sys.stderr)
        return 1

    print(f"Source URL: {args.source_url}")
    print(f"Ticker count: {len(tickers)}")
    print(f"Output file: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

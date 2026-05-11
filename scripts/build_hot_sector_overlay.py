#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
for path in (SRC_ROOT, PROJECT_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from screener.overlay.hot_sector import build_hot_sector_overlay, write_hot_sector_overlay


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a hot-sector overlay universe JSON artifact.")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("output/overlays/hot-sector-overlay.json"),
        help="Path to write the overlay JSON artifact.",
    )
    parser.add_argument("--max-sectors", type=int, default=3, help="Maximum number of sectors to include.")
    parser.add_argument("--per-sector-cap", type=int, default=4, help="Maximum number of tickers to take from each selected sector basket.")
    parser.add_argument("--benchmark", default="QQQ", help="Benchmark ticker used for relative strength comparison.")
    parser.add_argument("--lookback-short", type=int, default=20, help="Short lookback window in trading days.")
    parser.add_argument("--lookback-long", type=int, default=60, help="Long lookback window in trading days.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = build_hot_sector_overlay(
        benchmark_ticker=args.benchmark,
        max_sectors=args.max_sectors,
        per_sector_cap=args.per_sector_cap,
        lookback_short=args.lookback_short,
        lookback_long=args.lookback_long,
    )
    path = write_hot_sector_overlay(args.output, result)
    print(f"Overlay written: {path}")
    print(f"Selected sectors: {', '.join(result.selected_sectors) if result.selected_sectors else '(none)'}")
    print(f"Overlay tickers: {', '.join(result.selected_tickers) if result.selected_tickers else '(none)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Iterator

DEFAULT_OUTPUT_ROOT = Path("output/backfill")


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def parse_iso_date(value: str) -> date:
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Date must be YYYY-MM-DD.") from exc
    if parsed.isoformat() != value:
        raise argparse.ArgumentTypeError("Date must be YYYY-MM-DD.")
    return parsed


def iter_backfill_dates(start_date: date, end_date: date) -> Iterator[date]:
    if start_date > end_date:
        raise ValueError("start-date must be on or before end-date.")
    current = start_date
    while current <= end_date:
        yield current
        current += timedelta(days=1)


def resolve_output_root(root: Path, output_root: Path | None) -> Path:
    if output_root is None:
        return (root / DEFAULT_OUTPUT_ROOT).resolve()
    if output_root.is_absolute():
        return output_root.resolve()
    return (root / output_root).resolve()


def build_daily_command(
    python_path: Path,
    daily_script: Path,
    run_date: date,
    output_root: Path,
    *,
    dry_run: bool,
    skip_install: bool,
) -> list[str]:
    command = [
        str(python_path),
        str(daily_script),
        "--date",
        run_date.isoformat(),
        "--output-root",
        str(output_root),
        "--skip-assistant-briefing",
    ]
    if dry_run:
        command.append("--dry-run")
    if skip_install:
        command.append("--skip-install")
    return command


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run NASDAQ daily backfills over a date range.")
    parser.add_argument("--start-date", type=parse_iso_date, required=True, help="Inclusive backfill start date (YYYY-MM-DD).")
    parser.add_argument("--end-date", type=parse_iso_date, required=True, help="Inclusive backfill end date (YYYY-MM-DD).")
    parser.add_argument(
        "--output-root",
        type=Path,
        default=None,
        help="Root directory for backfill outputs. Defaults to output/backfill under the repo root.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print planned runs without executing them.")
    parser.add_argument(
        "--skip-install",
        action="store_true",
        help="Forward --skip-install to the daily wrapper for each run.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = project_root()
    output_root = resolve_output_root(root, args.output_root)
    daily_script = (root / "scripts" / "run_daily.py").resolve()
    dates = list(iter_backfill_dates(args.start_date, args.end_date))

    if args.dry_run:
        print(f"Backfill output root: {output_root}")
        for run_date in dates:
            output_dir = (output_root / run_date.isoformat()).resolve()
            command = build_daily_command(
                Path(sys.executable),
                daily_script,
                run_date,
                output_root,
                dry_run=True,
                skip_install=args.skip_install,
            )
            print(f"{run_date.isoformat()} -> {output_dir}")
            print("  " + shlex.join(command))
        return 0

    output_root.mkdir(parents=True, exist_ok=True)
    for run_date in dates:
        output_dir = output_root / run_date.isoformat()
        command = build_daily_command(
            sys.executable,
            daily_script,
            run_date,
            output_root,
            dry_run=False,
            skip_install=args.skip_install,
        )
        print(f"Running {run_date.isoformat()} -> {output_dir}")
        completed = subprocess.run(command, cwd=root)
        if completed.returncode != 0:
            print(f"Backfill stopped on {run_date.isoformat()} with exit code {completed.returncode}.", file=sys.stderr)
            return completed.returncode
    return 0


if __name__ == "__main__":
    sys.exit(main())

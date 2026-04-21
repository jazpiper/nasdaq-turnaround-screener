#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from screener.config import get_settings
from screener.intraday_ops import DEFAULT_COLLECTOR_COMMAND_TEMPLATE, IntradayPlan, build_collector_command, intraday_output_dir
from scripts.run_daily import ensure_venv, project_root


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Cron-friendly staged intraday collector runner.")
    parser.add_argument("--date", dest="run_date", default=date.today().isoformat(), help="Run date in YYYY-MM-DD format. Defaults to today.")
    parser.add_argument("--window-id", required=True, help="Configured intraday window identifier, for example open-1 or power-hour-2.")
    parser.add_argument("--output-root", type=Path, default=None, help="Root directory for staged intraday outputs. Defaults to config/env setting.")
    parser.add_argument("--collector-command", default=None, help="Collector command template. Overrides SCREENER_INTRADAY_COLLECTOR_COMMAND.")
    parser.add_argument("--skip-install", action="store_true", help="Create/use .venv but skip dependency installation.")
    parser.add_argument("--persist-oracle-sql", action="store_true", help="Write successful collection results to Oracle SQL.")
    return parser.parse_args()


def resolve_collector_command(args: argparse.Namespace, settings_command: str | None) -> str:
    command = args.collector_command or settings_command or DEFAULT_COLLECTOR_COMMAND_TEMPLATE
    return command


def main() -> int:
    args = parse_args()
    root = project_root()
    settings = get_settings()
    output_root = (root / (args.output_root or settings.intraday_output_root)).resolve()
    plan = IntradayPlan(window_ids=settings.intraday_window_ids)
    window_id = plan.validate_window_id(args.window_id)
    window_index = plan.window_ids.index(window_id)
    output_dir = intraday_output_dir(output_root, args.run_date, window_id)

    python_path = ensure_venv(root, skip_install=args.skip_install)
    command_template = resolve_collector_command(args, settings.intraday_collector_command)
    if args.persist_oracle_sql and "--persist-oracle-sql" not in command_template:
        command_template = f"{command_template} --persist-oracle-sql"
    command = build_collector_command(
        command_template=command_template,
        python_path=python_path,
        run_date=args.run_date,
        window_id=window_id,
        window_index=window_index,
        output_dir=output_dir,
        output_root=output_root,
        project_root=root,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"Intraday date: {args.run_date}")
    print(f"Window id: {window_id}")
    print(f"Output dir: {output_dir}")
    print(f"Collector command: {' '.join(command)}")

    completed = subprocess.run(command, cwd=root)
    return completed.returncode


if __name__ == "__main__":
    sys.exit(main())

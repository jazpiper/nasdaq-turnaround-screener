#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import venv
from datetime import date
from pathlib import Path

DEFAULT_OUTPUT_ROOT = Path("output/daily")
DEFAULT_CUSTOM_UNIVERSE_NAME = "user-watchlist"
LATEST_NAME = "latest"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Cron-friendly NASDAQ screener runner.")
    parser.add_argument("--date", dest="run_date", default=date.today().isoformat(), help="Run date in YYYY-MM-DD format. Defaults to today.")
    parser.add_argument(
        "--output-root",
        type=Path,
        default=None,
        help="Root directory for dated run outputs. Defaults to output/daily, or output/daily-<universe-name> when --tickers is provided.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Run the screener without writing report artifacts.")
    parser.add_argument("--skip-install", action="store_true", help="Create/use .venv but skip dependency installation.")
    parser.add_argument("--use-staged-intraday", action="store_true", help="Prefer latest staged intraday quotes for same-day enrichment when available.")
    parser.add_argument("--intraday-output-root", type=Path, default=None, help="Override intraday artifact root used with --use-staged-intraday.")
    parser.add_argument("--persist-oracle-sql", action="store_true", help="Write successful daily run results to Oracle SQL.")
    parser.add_argument("--universe-name", default=None, help="Name to record for a custom ticker universe.")
    parser.add_argument("--tickers", "--universe-tickers", dest="universe_tickers", default=None, help="Comma-separated tickers for a custom screener universe.")
    return parser.parse_args()


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def venv_python(root: Path) -> Path:
    if os.name == "nt":
        return root / ".venv" / "Scripts" / "python.exe"
    return root / ".venv" / "bin" / "python"


def ensure_venv(root: Path, skip_install: bool = False) -> Path:
    python_path = venv_python(root)
    if skip_install:
        if not python_path.exists():
            builder = venv.EnvBuilder(with_pip=True)
            builder.create(root / ".venv")
        return python_path

    uv_path = shutil.which("uv")
    if uv_path is None:
        raise RuntimeError("uv is required. Install uv, then run `uv sync --extra dev`.")

    subprocess.run(
        [uv_path, "sync", "--extra", "dev"],
        cwd=root,
        check=True,
    )
    if not python_path.exists():
        builder = venv.EnvBuilder(with_pip=True)
        builder.create(root / ".venv")
    return python_path


def dated_output_dir(output_root: Path, run_date: str) -> Path:
    return output_root / run_date


def resolve_output_root(
    output_root: Path | None,
    *,
    universe_name: str | None = None,
    universe_tickers: str | None = None,
) -> Path:
    if output_root is not None:
        return output_root
    if universe_tickers is None:
        return DEFAULT_OUTPUT_ROOT
    suffix = _safe_output_root_suffix(universe_name or DEFAULT_CUSTOM_UNIVERSE_NAME)
    return DEFAULT_OUTPUT_ROOT.with_name(f"{DEFAULT_OUTPUT_ROOT.name}-{suffix}")


def _safe_output_root_suffix(value: str) -> str:
    normalized = "".join(character.lower() if character.isalnum() else "-" for character in value.strip())
    collapsed = "-".join(part for part in normalized.split("-") if part)
    return collapsed or DEFAULT_CUSTOM_UNIVERSE_NAME


def update_latest_pointer(output_root: Path, target_dir: Path) -> Path:
    latest_path = output_root / LATEST_NAME
    if latest_path.exists() or latest_path.is_symlink():
        if latest_path.is_dir() and not latest_path.is_symlink():
            shutil.rmtree(latest_path)
        else:
            latest_path.unlink()

    relative_target = Path(target_dir.name)
    try:
        latest_path.symlink_to(relative_target, target_is_directory=True)
    except OSError:
        latest_path.mkdir(parents=True, exist_ok=True)
        for entry in target_dir.iterdir():
            destination = latest_path / entry.name
            if destination.exists() or destination.is_symlink():
                if destination.is_dir() and not destination.is_symlink():
                    shutil.rmtree(destination)
                else:
                    destination.unlink()
            if entry.is_dir():
                shutil.copytree(entry, destination)
            else:
                shutil.copy2(entry, destination)
    return latest_path


def run_screener(
    python_path: Path,
    root: Path,
    run_date: str,
    output_dir: Path,
    dry_run: bool,
    use_staged_intraday: bool,
    intraday_output_root: Path | None,
    persist_oracle_sql: bool,
    universe_name: str | None = None,
    universe_tickers: str | None = None,
) -> int:
    command = [
        str(python_path),
        "-m",
        "screener.cli.main",
        "run",
        "--date",
        run_date,
        "--output-dir",
        str(output_dir),
    ]
    if dry_run:
        command.append("--dry-run")
    if use_staged_intraday:
        command.append("--use-staged-intraday")
    if intraday_output_root is not None:
        command.extend(["--intraday-output-root", str(intraday_output_root)])
    if persist_oracle_sql:
        command.append("--persist-oracle-sql")
    if universe_name is not None:
        command.extend(["--universe-name", universe_name])
    if universe_tickers is not None:
        command.extend(["--tickers", universe_tickers])

    completed = subprocess.run(command, cwd=root)
    return completed.returncode


def main() -> int:
    args = parse_args()
    root = project_root()
    output_root = (
        root
        / resolve_output_root(
            args.output_root,
            universe_name=args.universe_name,
            universe_tickers=args.universe_tickers,
        )
    ).resolve()
    output_dir = dated_output_dir(output_root, args.run_date)

    python_path = ensure_venv(root, skip_install=args.skip_install)
    exit_code = run_screener(
        python_path,
        root,
        args.run_date,
        output_dir,
        args.dry_run,
        args.use_staged_intraday,
        args.intraday_output_root,
        args.persist_oracle_sql,
        args.universe_name,
        args.universe_tickers,
    )
    if exit_code != 0:
        return exit_code

    if not args.dry_run:
        latest_path = update_latest_pointer(output_root, output_dir)
        print(f"Daily output: {output_dir}")
        print(f"Latest output: {latest_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

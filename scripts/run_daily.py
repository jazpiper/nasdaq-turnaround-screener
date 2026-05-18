#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import venv
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
for path in (SRC_ROOT, PROJECT_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from screener.dates import resolve_ny_run_date

DEFAULT_OUTPUT_ROOT = Path("output/daily")
DEFAULT_CUSTOM_UNIVERSE_NAME = "user-watchlist"
DEFAULT_ASSISTANT_USER_TICKERS = "TSLA,INFQ,PLTR,RKLB,GOOGL,NVDA"
LATEST_NAME = "latest"
DEFAULT_CRON_DELAY_WARNING_SECONDS = 15 * 60


def resolve_run_date(value: str | None, *, clock=None) -> str:
    try:
        return resolve_ny_run_date(value, clock=clock)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Cron-friendly NASDAQ screener runner.")
    parser.add_argument(
        "--date",
        dest="run_date",
        type=resolve_run_date,
        default=resolve_run_date(None),
        help="Run date as YYYY-MM-DD, 'auto', or 'ny-today'. Defaults to America/New_York today.",
    )
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
    parser.add_argument("--overlay-tickers", default=None, help="Comma-separated hot-sector overlay tickers to append to the core universe.")
    parser.add_argument("--overlay-file", type=Path, default=None, help="File containing overlay tickers as JSON, CSV, or newline-separated text.")
    parser.add_argument("--overlay-name", default=None, help="Label used when naming outputs for an overlay-backed universe.")
    parser.add_argument(
        "--skip-assistant-briefing",
        action="store_true",
        help="Do not build compact assistant briefing artifacts after a successful non-dry run.",
    )
    parser.add_argument(
        "--assistant-user-tickers",
        default=DEFAULT_ASSISTANT_USER_TICKERS,
        help="Comma-separated holdings/watchlist tickers for assistant briefing artifacts. Custom --tickers runs use --tickers unless this is explicitly set.",
    )
    parser.add_argument(
        "--assistant-output-dir",
        type=Path,
        default=Path("output/assistant"),
        help="Directory for compact assistant briefing artifacts.",
    )
    parser.add_argument(
        "--assistant-artifact-basename",
        default=None,
        help="Optional assistant briefing artifact basename; writes <basename>.json and <basename>.md.",
    )
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
    overlay_tickers: str | None = None,
    overlay_file: Path | None = None,
    overlay_name: str | None = None,
) -> Path:
    if output_root is not None:
        return output_root
    has_custom_universe = universe_tickers is not None or overlay_tickers is not None or overlay_file is not None
    if not has_custom_universe:
        return DEFAULT_OUTPUT_ROOT
    suffix_base = universe_name or DEFAULT_CUSTOM_UNIVERSE_NAME
    if overlay_tickers is not None or overlay_file is not None:
        suffix_base = f"{suffix_base}-{overlay_name or (overlay_file.stem if overlay_file is not None else 'hot-sector-overlay')}"
    suffix = _safe_output_root_suffix(suffix_base)
    return DEFAULT_OUTPUT_ROOT.with_name(f"{DEFAULT_OUTPUT_ROOT.name}-{suffix}")


def _safe_output_root_suffix(value: str) -> str:
    normalized = "".join(character.lower() if character.isalnum() else "-" for character in value.strip())
    collapsed = "-".join(part for part in normalized.split("-") if part)
    return collapsed or DEFAULT_CUSTOM_UNIVERSE_NAME


def resolve_assistant_user_tickers(*, universe_tickers: str | None, assistant_user_tickers: str | None) -> str:
    if assistant_user_tickers and assistant_user_tickers != DEFAULT_ASSISTANT_USER_TICKERS:
        return assistant_user_tickers
    return universe_tickers or (assistant_user_tickers or DEFAULT_ASSISTANT_USER_TICKERS)


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


def write_cron_health(output_dir: Path, *, run_date: str, exit_code: int, started_at: datetime, completed_at: datetime) -> Path:
    metadata_path = output_dir / "run-metadata.json"
    metadata_available = metadata_path.exists()
    quality_gate = None
    quality_gate_reasons: list[str] = []
    observability: dict[str, object] = {}
    run_status = "success" if exit_code == 0 else "failed"
    metadata_read_error: str | None = None
    if metadata_available:
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            quality_gate = metadata.get("quality_gate")
            quality_gate_reasons = list(metadata.get("quality_gate_reasons") or [])
            run_status = str(metadata.get("run_status") or run_status)
            if isinstance(metadata.get("observability"), dict):
                observability = metadata["observability"]
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            metadata_read_error = exc.__class__.__name__
            quality_gate_reasons = ["metadata_unreadable"]
    elif exit_code != 0:
        quality_gate_reasons = ["screener_subprocess_failed_before_metadata"]

    duration_seconds = round((completed_at - started_at).total_seconds(), 3)
    attention_reasons = _cron_attention_reasons(
        exit_code=exit_code,
        quality_gate=quality_gate,
        quality_gate_reasons=quality_gate_reasons,
        duration_seconds=duration_seconds,
        metadata_read_error=metadata_read_error,
    )
    payload = {
        "run_date": run_date,
        "run_status": run_status,
        "exit_code": exit_code,
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
        "duration_seconds": duration_seconds,
        "metadata_path": str(metadata_path),
        "metadata_available": metadata_available,
        "metadata_read_error": metadata_read_error,
        "quality_gate": quality_gate,
        "quality_gate_reasons": quality_gate_reasons,
        "observability": observability,
        "attention_required": bool(attention_reasons),
        "attention_reasons": attention_reasons,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    health_path = output_dir / "cron-health.json"
    health_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return health_path


def update_cron_status_pointers(output_root: Path, health_path: Path) -> tuple[Path, Path | None]:
    latest_health_path = output_root / "latest-cron-health.json"
    health_text = health_path.read_text(encoding="utf-8")
    latest_health_path.write_text(health_text, encoding="utf-8")

    health = json.loads(health_text)
    if int(health.get("exit_code", 1)) != 0:
        return latest_health_path, None

    last_success_path = output_root / "last-success.json"
    last_success = {
        "run_date": health.get("run_date"),
        "completed_at": health.get("completed_at"),
        "duration_seconds": health.get("duration_seconds"),
        "cron_health_path": str(health_path),
        "output_dir": str(health_path.parent),
    }
    last_success_path.write_text(json.dumps(last_success, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return latest_health_path, last_success_path


def _cron_attention_reasons(
    *,
    exit_code: int,
    quality_gate: object,
    quality_gate_reasons: list[str],
    duration_seconds: float,
    metadata_read_error: str | None,
) -> list[str]:
    reasons: list[str] = []
    if exit_code != 0:
        reasons.append("exit_code_nonzero")
    if quality_gate in {"warn", "block"}:
        reasons.append(f"quality_gate_{quality_gate}")
    if metadata_read_error is not None:
        reasons.append("metadata_unreadable")
    if duration_seconds > DEFAULT_CRON_DELAY_WARNING_SECONDS:
        reasons.append("duration_seconds_gt_900")
    for reason in quality_gate_reasons:
        if reason not in reasons:
            reasons.append(reason)
    return reasons


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
    overlay_tickers: str | None = None,
    overlay_file: Path | None = None,
    overlay_name: str | None = None,
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
    if overlay_tickers is not None:
        command.extend(["--overlay-tickers", overlay_tickers])
    if overlay_file is not None:
        command.extend(["--overlay-file", str(overlay_file)])
    if overlay_name is not None:
        command.extend(["--overlay-name", overlay_name])

    completed = subprocess.run(command, cwd=root)
    return completed.returncode


def run_assistant_briefing(
    python_path: Path,
    root: Path,
    report_path: Path,
    output_dir: Path,
    user_tickers: str,
    artifact_basename: str | None = None,
) -> int:
    command = [
        str(python_path),
        "-m",
        "screener.cli.main",
        "build-assistant-briefing",
        "--report-path",
        str(report_path),
        "--output-dir",
        str(output_dir),
        "--user-tickers",
        user_tickers,
    ]
    if artifact_basename is not None:
        command.extend(["--artifact-basename", artifact_basename])

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
            overlay_tickers=args.overlay_tickers,
            overlay_file=args.overlay_file,
            overlay_name=args.overlay_name,
        )
    ).resolve()
    output_dir = dated_output_dir(output_root, args.run_date)

    python_path = ensure_venv(root, skip_install=args.skip_install)
    started_at = datetime.now(UTC)
    health_path: Path | None = None
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
        args.overlay_tickers,
        args.overlay_file,
        args.overlay_name,
    )
    completed_at = datetime.now(UTC)
    if not args.dry_run:
        health_path = write_cron_health(
            output_dir,
            run_date=args.run_date,
            exit_code=exit_code,
            started_at=started_at,
            completed_at=completed_at,
        )
        update_cron_status_pointers(output_root, health_path)
    if exit_code != 0:
        if health_path is not None:
            print(f"Cron health: {health_path}", file=sys.stderr)
        return exit_code

    if not args.dry_run:
        latest_path = update_latest_pointer(output_root, output_dir)
        print(f"Daily output: {output_dir}")
        print(f"Latest output: {latest_path}")

    if not args.skip_assistant_briefing and not args.dry_run:
        briefing_exit_code = run_assistant_briefing(
            python_path,
            root,
            output_dir / "daily-report.json",
            (root / args.assistant_output_dir).resolve(),
            resolve_assistant_user_tickers(
                universe_tickers=args.universe_tickers,
                assistant_user_tickers=args.assistant_user_tickers,
            ),
            artifact_basename=args.assistant_artifact_basename,
        )
        if briefing_exit_code != 0:
            return briefing_exit_code

    return 0


if __name__ == "__main__":
    sys.exit(main())

from __future__ import annotations

from pathlib import Path

from screener.alerts.schema import AlertDocument
from screener.storage.files import write_json_atomic


def build_daily_alert_paths(run_directory: Path, latest_directory: Path) -> tuple[Path, Path]:
    return run_directory / "alert-events.json", latest_directory / "alert-events.json"


def build_intraday_alert_paths(run_directory: Path, run_date: str) -> tuple[Path, Path]:
    date_root = run_directory.parents[2] / run_date
    return run_directory / "alert-events.json", date_root / "latest-alert-events.json"


def write_alert_document(run_path: Path, stable_path: Path | None, document: AlertDocument) -> tuple[Path, Path | None]:
    payload = document.model_dump(mode="json")
    write_json_atomic(run_path, payload)
    if stable_path is not None:
        write_json_atomic(stable_path, payload)
    return run_path, stable_path

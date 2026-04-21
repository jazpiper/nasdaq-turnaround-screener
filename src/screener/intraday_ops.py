from __future__ import annotations

import shlex
from dataclasses import dataclass
from pathlib import Path

DEFAULT_INTRADAY_WINDOW_IDS: tuple[str, ...] = (
    "open-1",
    "open-2",
    "midday-1",
    "midday-2",
    "power-hour-1",
    "power-hour-2",
)
DEFAULT_COLLECTOR_COMMAND_TEMPLATE = (
    "{python} -m screener.cli.collect_intraday "
    "--date {date} --window-id {window_id} --output-dir {output_dir}"
)


@dataclass(frozen=True, slots=True)
class IntradayPlan:
    window_ids: tuple[str, ...]

    def validate_window_id(self, window_id: str) -> str:
        normalized = normalize_window_id(window_id)
        if normalized not in self.window_ids:
            available = ", ".join(self.window_ids)
            raise ValueError(f"Unknown window id '{window_id}'. Expected one of: {available}")
        return normalized


def normalize_window_id(value: str) -> str:
    normalized = value.strip().lower()
    if not normalized:
        raise ValueError("window id must not be empty")
    return normalized


def parse_window_ids(value: str | None) -> tuple[str, ...]:
    if value is None:
        return DEFAULT_INTRADAY_WINDOW_IDS
    window_ids = tuple(normalize_window_id(part) for part in value.split(",") if part.strip())
    if not window_ids:
        raise ValueError("window ids must include at least one non-empty value")
    return window_ids


def intraday_output_dir(output_root: Path, run_date: str, window_id: str) -> Path:
    return output_root / run_date / normalize_window_id(window_id)


def build_collector_command(
    *,
    command_template: str,
    python_path: Path,
    run_date: str,
    window_id: str,
    output_dir: Path,
    project_root: Path,
) -> list[str]:
    formatted = command_template.format(
        python=shlex.quote(str(python_path)),
        date=shlex.quote(run_date),
        window_id=shlex.quote(normalize_window_id(window_id)),
        output_dir=shlex.quote(str(output_dir)),
        project_root=shlex.quote(str(project_root)),
    )
    return shlex.split(formatted)

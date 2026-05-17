from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from screener.models import PreviousCandidateOutcome


def build_previous_candidate_outcomes(
    *,
    current_run_date: str,
    current_closes: dict[str, float],
    daily_output_root: Path,
) -> list[PreviousCandidateOutcome]:
    previous_report_path = _find_previous_daily_report(daily_output_root, current_run_date)
    if previous_report_path is None:
        return []

    try:
        payload = json.loads(previous_report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []

    outcomes: list[PreviousCandidateOutcome] = []
    for candidate in payload.get("candidates", []):
        if not isinstance(candidate, dict):
            continue
        ticker = str(candidate.get("ticker") or "").strip().upper()
        if not ticker:
            continue
        previous_close = _as_float(candidate.get("close"))
        current_close = current_closes.get(ticker)
        absolute_return: float | None = None
        percent_return: float | None = None
        if previous_close is not None and current_close is not None:
            absolute_return = round(current_close - previous_close, 4)
            if previous_close != 0:
                percent_return = round((current_close - previous_close) / previous_close * 100, 2)
        outcomes.append(
            PreviousCandidateOutcome(
                ticker=ticker,
                name=_as_optional_str(candidate.get("name")),
                previous_close=previous_close,
                current_close=current_close,
                absolute_return=absolute_return,
                percent_return=percent_return,
                previous_score=_as_int(candidate.get("score")),
                previous_risk_adjusted_score=_as_int(candidate.get("risk_adjusted_score")),
                previous_tier=_as_optional_str(candidate.get("tier")),
            )
        )
    return outcomes


def _find_previous_daily_report(daily_output_root: Path, current_run_date: str) -> Path | None:
    if not daily_output_root.exists():
        return None
    candidates: list[tuple[str, Path]] = []
    for child in daily_output_root.iterdir():
        if not child.is_dir():
            continue
        run_date = child.name
        if run_date == "latest" or run_date >= current_run_date:
            continue
        report_path = child / "daily-report.json"
        if report_path.exists():
            candidates.append((run_date, report_path))
    if not candidates:
        return None
    return max(candidates, key=lambda item: item[0])[1]


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None

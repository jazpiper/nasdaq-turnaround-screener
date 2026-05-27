from __future__ import annotations

import sys

from scripts import run_nasdaq_expanded_discovery as discovery


def test_main_builds_recommendations_from_dated_report_path(monkeypatch) -> None:
    commands: list[list[str]] = []

    monkeypatch.setattr(
        sys,
        "argv",
        ["run_nasdaq_expanded_discovery.py", "--date", "2026-05-19", "--skip-install"],
    )
    monkeypatch.setattr(discovery, "ensure_ticker_file", lambda *args, **kwargs: None)
    monkeypatch.setattr(discovery, "run", lambda command: commands.append(command))

    assert discovery.main() == 0

    assert commands[0][0] == sys.executable
    assert commands[0][1:4] == ["scripts/run_daily.py", "--date", "2026-05-19"]
    recommendation_command = commands[1]
    report_path = recommendation_command[recommendation_command.index("--daily-report-path") + 1]
    assert report_path.endswith("output/daily-nasdaq-expanded-500/2026-05-19/daily-report.json")
    assert "/latest/" not in report_path


def test_main_resolves_auto_date_once_for_daily_and_recommendation(monkeypatch) -> None:
    commands: list[list[str]] = []

    monkeypatch.setattr(
        sys,
        "argv",
        ["run_nasdaq_expanded_discovery.py", "--date", "ny-today", "--skip-install"],
    )
    monkeypatch.setattr(discovery, "ensure_ticker_file", lambda *args, **kwargs: None)
    monkeypatch.setattr(discovery, "resolve_ny_run_date", lambda value: "2026-05-26")
    monkeypatch.setattr(discovery, "run", lambda command: commands.append(command))

    assert discovery.main() == 0

    assert commands[0][commands[0].index("--date") + 1] == "2026-05-26"
    recommendation_command = commands[1]
    report_path = recommendation_command[recommendation_command.index("--daily-report-path") + 1]
    assert report_path.endswith("output/daily-nasdaq-expanded-500/2026-05-26/daily-report.json")

from __future__ import annotations

from argparse import Namespace
from datetime import date
from pathlib import Path

from scripts import run_backfill


def test_iter_backfill_dates_is_inclusive() -> None:
    dates = list(run_backfill.iter_backfill_dates(date(2026, 4, 20), date(2026, 4, 22)))

    assert dates == [date(2026, 4, 20), date(2026, 4, 21), date(2026, 4, 22)]


def test_iter_backfill_dates_rejects_inverted_range() -> None:
    try:
        list(run_backfill.iter_backfill_dates(date(2026, 4, 22), date(2026, 4, 20)))
    except ValueError as exc:
        assert str(exc) == "start-date must be on or before end-date."
    else:
        raise AssertionError("Expected ValueError for inverted date range")


def test_resolve_output_root_defaults_under_repo_root(tmp_path: Path) -> None:
    assert run_backfill.resolve_output_root(tmp_path, None) == (tmp_path / "output/backfill").resolve()


def test_build_daily_command_targets_daily_wrapper(tmp_path: Path) -> None:
    command = run_backfill.build_daily_command(
        Path("/usr/bin/python3"),
        tmp_path / "scripts/run_daily.py",
        date(2026, 4, 21),
        tmp_path / "output/backfill",
        dry_run=True,
        skip_install=True,
    )

    assert command == [
        "/usr/bin/python3",
        str(tmp_path / "scripts/run_daily.py"),
        "--date",
        "2026-04-21",
        "--output-root",
        str(tmp_path / "output/backfill"),
        "--skip-assistant-briefing",
        "--dry-run",
        "--skip-install",
    ]


def test_main_dry_run_prints_plan_and_skips_subprocess(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setattr(run_backfill, "project_root", lambda: tmp_path)
    monkeypatch.setattr(
        run_backfill,
        "parse_args",
        lambda: Namespace(
            start_date=date(2026, 4, 20),
            end_date=date(2026, 4, 21),
            output_root=None,
            dry_run=True,
            skip_install=False,
        ),
    )
    calls: list[object] = []
    monkeypatch.setattr(run_backfill.subprocess, "run", lambda *args, **kwargs: calls.append((args, kwargs)))

    assert run_backfill.main() == 0
    assert calls == []

    stdout = capsys.readouterr().out
    assert f"Backfill output root: {(tmp_path / 'output/backfill').resolve()}" in stdout
    assert "2026-04-20 ->" in stdout
    assert "2026-04-21 ->" in stdout
    assert "--skip-assistant-briefing" in stdout
    assert "--dry-run" in stdout

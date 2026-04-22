from __future__ import annotations

import argparse
import sys

import pytest

from scripts import run_intraday_window


def test_parse_run_date_accepts_canonical_iso_value() -> None:
    assert run_intraday_window.parse_run_date("2026-04-21") == "2026-04-21"


def test_parse_run_date_rejects_path_like_value() -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        run_intraday_window.parse_run_date("../../tmp/owned")


def test_main_rejects_invalid_date_before_resolving_output_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_intraday_output_dir(*args: object, **kwargs: object) -> None:
        raise AssertionError("intraday_output_dir should not be called for an invalid date")

    def fail_ensure_venv(*args: object, **kwargs: object) -> None:
        raise AssertionError("ensure_venv should not be called for an invalid date")

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_intraday_window.py",
            "--date",
            "../../tmp/owned",
            "--window-id",
            "open-1",
        ],
    )
    monkeypatch.setattr(run_intraday_window, "intraday_output_dir", fail_intraday_output_dir)
    monkeypatch.setattr(run_intraday_window, "ensure_venv", fail_ensure_venv)

    with pytest.raises(SystemExit) as exc_info:
        run_intraday_window.main()

    assert exc_info.value.code == 2

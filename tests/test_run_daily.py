from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from scripts import run_daily
from scripts.run_daily import (
    DEFAULT_ASSISTANT_USER_TICKERS,
    DEFAULT_OUTPUT_ROOT,
    LATEST_NAME,
    dated_output_dir,
    resolve_assistant_user_tickers,
    resolve_run_date,
    resolve_output_root,
    update_cron_status_pointers,
    update_latest_pointer,
    write_cron_health,
)


def test_dated_output_dir_uses_run_date() -> None:
    output_root = Path("output/daily")

    assert dated_output_dir(output_root, "2026-04-21") == Path("output/daily/2026-04-21")


def test_resolve_run_date_defaults_to_new_york_date() -> None:
    clock = lambda: datetime(2026, 5, 5, 8, 30, tzinfo=ZoneInfo("Asia/Seoul"))

    assert resolve_run_date(None, clock=clock) == "2026-05-04"


def test_resolve_run_date_accepts_auto_aliases() -> None:
    clock = lambda: datetime(2026, 5, 5, 8, 30, tzinfo=ZoneInfo("Asia/Seoul"))

    assert resolve_run_date("auto", clock=clock) == "2026-05-04"
    assert resolve_run_date("ny-today", clock=clock) == "2026-05-04"


def test_resolve_run_date_preserves_explicit_iso_date() -> None:
    clock = lambda: datetime(2026, 5, 5, 8, 30, tzinfo=ZoneInfo("Asia/Seoul"))

    assert resolve_run_date("2026-05-05", clock=clock) == "2026-05-05"


def test_resolve_output_root_keeps_nasdaq_default() -> None:
    assert resolve_output_root(None) == DEFAULT_OUTPUT_ROOT


def test_resolve_output_root_separates_custom_watchlist_default() -> None:
    assert resolve_output_root(
        None,
        universe_name="user-watchlist",
        universe_tickers="TSLA,INFQ,PLTR,RKLB,GOOGL,NVDA",
    ) == Path("output/daily-user-watchlist")


def test_resolve_output_root_separates_overlay_backed_universe() -> None:
    assert resolve_output_root(
        None,
        universe_name="NASDAQ-100",
        overlay_tickers="NVDA,AMD,AVGO",
        overlay_name="hot-sector-overlay",
    ) == Path("output/daily-nasdaq-100-hot-sector-overlay")


def test_resolve_output_root_preserves_explicit_root_for_custom_watchlist() -> None:
    assert resolve_output_root(
        Path("output/daily"),
        universe_name="user-watchlist",
        universe_tickers="TSLA,NVDA",
    ) == Path("output/daily")


def test_resolve_output_root_sanitizes_custom_universe_name() -> None:
    assert resolve_output_root(
        None,
        universe_name="Personal Watchlist/Tech",
        universe_tickers="TSLA,NVDA",
    ) == Path("output/daily-personal-watchlist-tech")


def test_resolve_assistant_user_tickers_uses_default_for_core_universe() -> None:
    assert (
        resolve_assistant_user_tickers(
            universe_tickers=None,
            assistant_user_tickers=DEFAULT_ASSISTANT_USER_TICKERS,
        )
        == DEFAULT_ASSISTANT_USER_TICKERS
    )


def test_resolve_assistant_user_tickers_uses_custom_universe_when_not_overridden() -> None:
    assert (
        resolve_assistant_user_tickers(
            universe_tickers="TSLA,NVDA",
            assistant_user_tickers=DEFAULT_ASSISTANT_USER_TICKERS,
        )
        == "TSLA,NVDA"
    )


def test_resolve_assistant_user_tickers_preserves_explicit_override() -> None:
    assert (
        resolve_assistant_user_tickers(
            universe_tickers="TSLA,NVDA",
            assistant_user_tickers="AAPL,MSFT",
        )
        == "AAPL,MSFT"
    )


def test_update_latest_pointer_creates_symlink(tmp_path: Path) -> None:
    output_root = tmp_path / "daily"
    target_dir = output_root / "2026-04-21"
    target_dir.mkdir(parents=True)
    (target_dir / "daily-report.md").write_text("# report\n", encoding="utf-8")

    latest_path = update_latest_pointer(output_root, target_dir)

    assert latest_path == output_root / LATEST_NAME
    assert latest_path.is_symlink()
    assert latest_path.resolve() == target_dir.resolve()
    assert (latest_path / "daily-report.md").read_text(encoding="utf-8") == "# report\n"


def test_update_latest_pointer_exposes_alert_sidecar(tmp_path: Path) -> None:
    output_root = tmp_path / "daily"
    target_dir = output_root / "2026-04-21"
    target_dir.mkdir(parents=True)
    (target_dir / "daily-report.md").write_text("# report\n", encoding="utf-8")
    (target_dir / "alert-events.json").write_text('{"phase":"final"}\n', encoding="utf-8")

    latest_path = update_latest_pointer(output_root, target_dir)

    assert (latest_path / "alert-events.json").read_text(encoding="utf-8") == '{"phase":"final"}\n'


def test_write_cron_health_records_quality_gate_from_metadata(tmp_path: Path) -> None:
    output_dir = tmp_path / "daily" / "2026-05-01"
    output_dir.mkdir(parents=True)
    (output_dir / "run-metadata.json").write_text(
        json.dumps({"run_status": "success", "quality_gate": "warn", "quality_gate_reasons": ["failed_ticker_count_gt_5"]}),
        encoding="utf-8",
    )
    started_at = datetime(2026, 5, 1, 12, 0, tzinfo=ZoneInfo("UTC"))
    completed_at = datetime(2026, 5, 1, 12, 0, 7, tzinfo=ZoneInfo("UTC"))

    health_path = write_cron_health(
        output_dir,
        run_date="2026-05-01",
        exit_code=0,
        started_at=started_at,
        completed_at=completed_at,
    )

    payload = json.loads(health_path.read_text(encoding="utf-8"))
    assert payload["run_status"] == "success"
    assert payload["quality_gate"] == "warn"
    assert payload["quality_gate_reasons"] == ["failed_ticker_count_gt_5"]
    assert payload["duration_seconds"] == 7.0
    assert payload["metadata_available"] is True
    assert payload["observability"] == {}
    assert payload["attention_required"] is True
    assert payload["attention_reasons"] == ["quality_gate_warn", "failed_ticker_count_gt_5"]


def test_write_cron_health_records_pre_metadata_failure(tmp_path: Path) -> None:
    started_at = datetime(2026, 5, 1, 12, 0, tzinfo=ZoneInfo("UTC"))
    completed_at = datetime(2026, 5, 1, 12, 0, 3, tzinfo=ZoneInfo("UTC"))

    health_path = write_cron_health(
        tmp_path,
        run_date="2026-05-01",
        exit_code=2,
        started_at=started_at,
        completed_at=completed_at,
    )

    payload = json.loads(health_path.read_text(encoding="utf-8"))
    assert payload["run_status"] == "failed"
    assert payload["exit_code"] == 2
    assert payload["quality_gate_reasons"] == ["screener_subprocess_failed_before_metadata"]
    assert payload["metadata_available"] is False
    assert payload["attention_required"] is True
    assert payload["attention_reasons"] == ["exit_code_nonzero", "screener_subprocess_failed_before_metadata"]


def test_update_cron_status_pointers_records_latest_and_last_success(tmp_path: Path) -> None:
    output_dir = tmp_path / "daily" / "2026-05-01"
    started_at = datetime(2026, 5, 1, 12, 0, tzinfo=ZoneInfo("UTC"))
    completed_at = datetime(2026, 5, 1, 12, 2, tzinfo=ZoneInfo("UTC"))
    health_path = write_cron_health(
        output_dir,
        run_date="2026-05-01",
        exit_code=0,
        started_at=started_at,
        completed_at=completed_at,
    )

    latest_health_path, last_success_path = update_cron_status_pointers(tmp_path / "daily", health_path)

    assert latest_health_path == tmp_path / "daily" / "latest-cron-health.json"
    assert json.loads(latest_health_path.read_text(encoding="utf-8"))["exit_code"] == 0
    assert last_success_path is not None
    assert last_success_path == tmp_path / "daily" / "last-success.json"
    last_success = json.loads(last_success_path.read_text(encoding="utf-8"))
    assert last_success == {
        "completed_at": completed_at.isoformat(),
        "cron_health_path": str(health_path),
        "duration_seconds": 120.0,
        "output_dir": str(output_dir),
        "run_date": "2026-05-01",
    }


def test_update_cron_status_pointers_does_not_overwrite_last_success_on_failure(tmp_path: Path) -> None:
    output_root = tmp_path / "daily"
    existing_success = output_root / "last-success.json"
    existing_success.parent.mkdir(parents=True)
    existing_success.write_text('{"run_date":"2026-04-30"}\n', encoding="utf-8")
    health_path = write_cron_health(
        output_root / "2026-05-01",
        run_date="2026-05-01",
        exit_code=1,
        started_at=datetime(2026, 5, 1, 12, 0, tzinfo=ZoneInfo("UTC")),
        completed_at=datetime(2026, 5, 1, 12, 1, tzinfo=ZoneInfo("UTC")),
    )

    latest_health_path, last_success_path = update_cron_status_pointers(output_root, health_path)

    assert json.loads(latest_health_path.read_text(encoding="utf-8"))["exit_code"] == 1
    assert last_success_path is None
    assert existing_success.read_text(encoding="utf-8") == '{"run_date":"2026-04-30"}\n'


def test_ensure_venv_installs_with_uv_sync(monkeypatch, tmp_path: Path) -> None:
    python_path = tmp_path / ".venv" / "bin" / "python"
    python_path.parent.mkdir(parents=True)
    python_path.touch()
    calls: list[tuple[list[str], Path, bool]] = []

    monkeypatch.setattr(run_daily, "venv_python", lambda root: python_path)
    monkeypatch.setattr(run_daily.shutil, "which", lambda name: "/usr/bin/uv" if name == "uv" else None)
    monkeypatch.setattr(
        run_daily.subprocess,
        "run",
        lambda command, cwd, check: calls.append((command, cwd, check)),
    )

    assert run_daily.ensure_venv(tmp_path) == python_path
    assert calls == [(["/usr/bin/uv", "sync", "--extra", "dev"], tmp_path, True)]


def test_run_screener_passes_custom_universe_args(monkeypatch, tmp_path: Path) -> None:
    calls: list[tuple[list[str], Path]] = []

    class Completed:
        returncode = 0

    def fake_run(command, cwd):
        calls.append((command, cwd))
        return Completed()

    monkeypatch.setattr(run_daily.subprocess, "run", fake_run)
    python_path = tmp_path / ".venv" / "bin" / "python"
    output_dir = tmp_path / "output" / "user-watchlist" / "2026-05-01"

    exit_code = run_daily.run_screener(
        python_path,
        tmp_path,
        "2026-05-01",
        output_dir,
        dry_run=False,
        use_staged_intraday=False,
        intraday_output_root=None,
        persist_oracle_sql=False,
        universe_name="user-watchlist",
        universe_tickers="TSLA,INFQ,PLTR,RKLB,GOOGL,NVDA",
        overlay_tickers="NVDA,AMD,AVGO",
        overlay_file=tmp_path / "hot-sector-overlay.json",
        overlay_name="hot-sector-overlay",
    )

    assert exit_code == 0
    assert calls == [
        (
            [
                str(python_path),
                "-m",
                "screener.cli.main",
                "run",
                "--date",
                "2026-05-01",
                "--output-dir",
                str(output_dir),
                "--universe-name",
                "user-watchlist",
                "--tickers",
                "TSLA,INFQ,PLTR,RKLB,GOOGL,NVDA",
                "--overlay-tickers",
                "NVDA,AMD,AVGO",
                "--overlay-file",
                str(tmp_path / "hot-sector-overlay.json"),
                "--overlay-name",
                "hot-sector-overlay",
            ],
            tmp_path,
        )
    ]


def test_run_assistant_briefing_passes_custom_universe_args(monkeypatch, tmp_path: Path) -> None:
    calls: list[tuple[list[str], Path]] = []

    class Completed:
        returncode = 0

    def fake_run(command, cwd):
        calls.append((command, cwd))
        return Completed()

    monkeypatch.setattr(run_daily.subprocess, "run", fake_run)
    python_path = tmp_path / ".venv" / "bin" / "python"
    report_path = tmp_path / "output" / "daily-user-watchlist" / "2026-05-01" / "daily-report.json"
    assistant_output_dir = tmp_path / "output" / "assistant"

    exit_code = run_daily.run_assistant_briefing(
        python_path,
        tmp_path,
        report_path,
        assistant_output_dir,
        "TSLA,INFQ,PLTR,RKLB,GOOGL,NVDA",
    )

    assert exit_code == 0
    assert calls == [
        (
            [
                str(python_path),
                "-m",
                "screener.cli.main",
                "build-assistant-briefing",
                "--report-path",
                str(report_path),
                "--output-dir",
                str(assistant_output_dir),
                "--user-tickers",
                "TSLA,INFQ,PLTR,RKLB,GOOGL,NVDA",
            ],
            tmp_path,
        )
    ]

from __future__ import annotations

from pathlib import Path

from scripts import run_daily
from scripts.run_daily import (
    DEFAULT_OUTPUT_ROOT,
    LATEST_NAME,
    dated_output_dir,
    resolve_output_root,
    update_latest_pointer,
)


def test_dated_output_dir_uses_run_date() -> None:
    output_root = Path("output/daily")

    assert dated_output_dir(output_root, "2026-04-21") == Path("output/daily/2026-04-21")


def test_resolve_output_root_keeps_nasdaq_default() -> None:
    assert resolve_output_root(None) == DEFAULT_OUTPUT_ROOT


def test_resolve_output_root_separates_custom_watchlist_default() -> None:
    assert resolve_output_root(
        None,
        universe_name="user-watchlist",
        universe_tickers="TSLA,INFQ,PLTR,RKLB,GOOGL,NVDA",
    ) == Path("output/daily-user-watchlist")


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
            ],
            tmp_path,
        )
    ]

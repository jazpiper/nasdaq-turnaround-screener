from __future__ import annotations

from pathlib import Path

from scripts.run_daily import LATEST_NAME, dated_output_dir, update_latest_pointer


def test_dated_output_dir_uses_run_date() -> None:
    output_root = Path("output/daily")

    assert dated_output_dir(output_root, "2026-04-21") == Path("output/daily/2026-04-21")


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

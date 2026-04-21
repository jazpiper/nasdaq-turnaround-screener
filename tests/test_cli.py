from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from screener.cli.main import app

runner = CliRunner()


def test_run_dry_run_skips_artifacts(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["run", "--date", "2026-04-21", "--dry-run", "--output-dir", str(tmp_path)],
    )

    assert result.exit_code == 0
    assert "Artifacts skipped" in result.stdout
    assert not any(tmp_path.iterdir())


def test_run_writes_artifacts(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["run", "--date", "2026-04-21", "--output-dir", str(tmp_path)],
    )

    assert result.exit_code == 0
    markdown_path = tmp_path / "daily-report.md"
    json_path = tmp_path / "daily-report.json"
    metadata_path = tmp_path / "run-metadata.json"

    assert markdown_path.exists()
    assert json_path.exists()
    assert metadata_path.exists()
    assert "PLACEHOLDER" in markdown_path.read_text(encoding="utf-8")

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["date"] == "2026-04-21"
    assert payload["candidate_count"] == 1
    assert payload["candidates"][0]["ticker"] == "PLACEHOLDER"

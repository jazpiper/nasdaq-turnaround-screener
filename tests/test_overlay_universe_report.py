from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from typer.testing import CliRunner

from screener.cli.main import app
from screener.reporting.overlay_universe_report import (
    DEFAULT_ARTIFACT_BASENAME,
    DEFAULT_BACKTEST_SUMMARY_PATH,
    DEFAULT_BASELINE_DAILY_REPORT_PATH,
    DEFAULT_OVERLAY_DAILY_REPORT_PATH,
    DEFAULT_OVERLAY_METADATA_PATH,
    build_overlay_universe_report_markdown,
    load_and_build_overlay_universe_report,
    write_overlay_universe_report,
)

runner = CliRunner()


def test_overlay_universe_report_payload_and_markdown(tmp_path: Path) -> None:
    payload, markdown = load_and_build_overlay_universe_report(
        baseline_report_path=DEFAULT_BASELINE_DAILY_REPORT_PATH,
        overlay_report_path=DEFAULT_OVERLAY_DAILY_REPORT_PATH,
        overlay_metadata_path=DEFAULT_OVERLAY_METADATA_PATH,
        backtest_summary_path=DEFAULT_BACKTEST_SUMMARY_PATH,
        output_dir=tmp_path,
        generated_at=datetime(2026, 5, 18, 12, 0, tzinfo=timezone.utc),
    )

    comparison = payload["comparison"]
    deltas = comparison["deltas"]

    assert comparison["baseline"]["candidate_count"] == 57
    assert comparison["overlay"]["candidate_count"] == 57
    expected_overlay_sectors = ["semiconductors", "technology", "consumer_discretionary"]
    expected_overlay_tickers = ["NVDA", "AVGO", "AMD", "QCOM", "MSFT", "AMZN", "TSLA", "BKNG", "COST"]
    overlay_metadata = json.loads(DEFAULT_OVERLAY_METADATA_PATH.read_text(encoding="utf-8"))

    assert deltas["planned_ticker_count"] == 0
    assert deltas["candidate_count"] == 0
    assert payload["overlay"]["selected_sectors"] == expected_overlay_sectors
    assert payload["overlay"]["tickers"] == expected_overlay_tickers
    assert payload["overlay"]["selected_sectors"] == overlay_metadata["selected_sectors"]
    assert payload["overlay"]["tickers"] == overlay_metadata["tickers"]
    assert [signal["sector"] for signal in payload["overlay"]["signals"] if signal["selected"]] == expected_overlay_sectors
    assert payload["backtest"]["available"] is True
    assert [variant["variant_id"] for variant in payload["universe_variants"]] == [
        "core-nasdaq-100",
        "nasdaq-100-plus-hot-sector-overlay",
        "user-watchlist-plus-hot-sector-overlay",
    ]
    assert payload["universe_variants"][1]["planned_ticker_count"] == 102
    assert payload["universe_variants"][2]["status"] == "template"
    assert "Overlay / Universe Comparison" in markdown
    assert "| Planned tickers | 102 | 102 | 0 |" in markdown
    assert "| Candidate count | 57 | 57 | 0 |" in markdown
    assert "semiconductors" in markdown
    assert "user-watchlist-plus-hot-sector-overlay" in markdown

    json_path, markdown_path = write_overlay_universe_report(
        payload,
        markdown,
        tmp_path,
        artifact_basename=DEFAULT_ARTIFACT_BASENAME,
    )
    assert json_path.exists()
    assert markdown_path.exists()
    written = json.loads(json_path.read_text(encoding="utf-8"))
    assert written["comparison"]["deltas"]["candidate_count"] == 0


def test_overlay_universe_report_command_writes_artifacts(tmp_path: Path) -> None:
    output_dir = tmp_path / "overlay-report"

    result = runner.invoke(
        app,
        [
            "overlay-universe-report",
            "--baseline-report-path",
            str(DEFAULT_BASELINE_DAILY_REPORT_PATH),
            "--overlay-report-path",
            str(DEFAULT_OVERLAY_DAILY_REPORT_PATH),
            "--overlay-metadata-path",
            str(DEFAULT_OVERLAY_METADATA_PATH),
            "--backtest-summary-path",
            str(DEFAULT_BACKTEST_SUMMARY_PATH),
            "--output-dir",
            str(output_dir),
        ],
    )

    assert result.exit_code == 0
    assert "Comparison: planned=102→102 (0), candidates=57→57 (0)" in result.stdout
    assert "Overlay sectors: semiconductors, technology, consumer_discretionary" in result.stdout
    assert (output_dir / "overlay-universe-report.json").exists()
    assert (output_dir / "overlay-universe-report.md").exists()

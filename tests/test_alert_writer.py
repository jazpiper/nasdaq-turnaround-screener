from __future__ import annotations

import json
from pathlib import Path

from screener.alerts.schema import AlertDocument, AlertEvent, AlertSource, AlertSummary
from screener.alerts.writer import build_daily_alert_paths, build_intraday_alert_paths, write_alert_document


def test_build_daily_alert_paths(tmp_path: Path) -> None:
    run_directory = tmp_path / "daily" / "2026-04-21"
    latest_directory = tmp_path / "daily" / "latest"

    run_path, stable_path = build_daily_alert_paths(run_directory, latest_directory)

    assert run_path == run_directory / "alert-events.json"
    assert stable_path == latest_directory / "alert-events.json"


def test_build_intraday_alert_paths(tmp_path: Path) -> None:
    run_directory = tmp_path / "intraday" / "2026-04-21" / "window-01-of-06" / "run-20260421T073000Z"

    run_path, stable_path = build_intraday_alert_paths(run_directory, "2026-04-21")

    assert run_path == run_directory / "alert-events.json"
    assert stable_path == tmp_path / "intraday" / "latest-alert-events.json"


def test_write_alert_document_writes_both_paths(tmp_path: Path) -> None:
    run_path = tmp_path / "alert-events.json"
    stable_path = tmp_path / "latest" / "alert-events.json"
    document = AlertDocument(
        schema_version=1,
        delivery_contract="openclaw-alert-events-v1",
        run_date="2026-04-21",
        generated_at="2026-04-21T07:30:00Z",
        run_mode="daily",
        phase="final",
        source=AlertSource(
            artifact_directory="/tmp/output",
            report_path="/tmp/output/daily-report.json",
            metadata_path="/tmp/output/run-metadata.json",
            window_index=None,
            window_number=None,
            total_windows=None,
        ),
        summary=AlertSummary(
            eligible_candidate_count=2,
            individual_event_count=1,
            digest_event_count=1,
            suppressed_candidate_count=0,
            quality_gate="pass",
        ),
        events=[
            AlertEvent(
                event_type="ticker_alert",
                phase="final",
                delivery_mode="single",
                delivery_priority="high",
                severity="info",
                dedupe_key="dedupe-1",
                group_key="group-1",
                change_status="new",
                change_reason_codes=["new"],
                message_summary="AAPL final alert",
                payload={"ticker": "AAPL", "score": 78},
            )
        ],
    )

    returned_run_path, returned_stable_path = write_alert_document(run_path, stable_path, document)

    assert returned_run_path == run_path
    assert returned_stable_path == stable_path
    assert json.loads(run_path.read_text(encoding="utf-8")) == document.model_dump(mode="json")
    assert json.loads(stable_path.read_text(encoding="utf-8")) == document.model_dump(mode="json")

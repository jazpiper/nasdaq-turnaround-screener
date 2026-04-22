from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from screener.alerts.state import AlertState, DigestAlertState, TickerAlertState, load_alert_state, save_alert_state
from screener.storage.files import write_json_atomic


def test_load_alert_state_returns_empty_defaults_for_missing_file(tmp_path: Path) -> None:
    state_path = tmp_path / "alert-state.json"

    state = load_alert_state(state_path)

    assert state == AlertState()


def test_save_alert_state_round_trips_and_cleans_up_temp_file(tmp_path: Path) -> None:
    state_path = tmp_path / "alert-state.json"
    expected = AlertState(
        run_date="2026-04-21",
        tickers={
            "AAPL": TickerAlertState(
                last_delivery_tier="primary",
                last_material_signature="sig-aapl",
                last_phase="daily",
                last_emitted_at=datetime(2026, 4, 21, 7, 30, tzinfo=timezone.utc),
                last_dedupe_key="aapl-dedupe",
            )
        },
        digest=DigestAlertState(
            last_digest_signature="digest-1",
            last_digest_dedupe_key="digest-dedupe-1",
        ),
    )

    saved_path = save_alert_state(state_path, expected)

    assert saved_path == state_path
    assert load_alert_state(state_path) == expected
    assert not list(tmp_path.glob("*.tmp"))


def test_write_json_atomic_replaces_existing_payload(tmp_path: Path) -> None:
    payload_path = tmp_path / "payload.json"
    payload_path.write_text("{\"old\": true}\n", encoding="utf-8")

    write_json_atomic(payload_path, {"new": True})

    assert payload_path.read_text(encoding="utf-8") == "{\n  \"new\": true\n}\n"
    assert not list(tmp_path.glob("*.tmp"))

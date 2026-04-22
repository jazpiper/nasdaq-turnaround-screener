from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import threading

from screener.alerts.state import AlertState, DigestAlertState, TickerAlertState, load_alert_state, save_alert_state
from screener.storage.files import write_json_atomic, write_text_atomic


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


def test_write_text_atomic_uses_unique_temp_files_for_concurrent_writers(tmp_path: Path, monkeypatch) -> None:
    payload_path = tmp_path / "alert-state.txt"
    first_replace_started = threading.Event()
    release_first_replace = threading.Event()
    seen_temp_names: list[str] = []
    errors: list[BaseException] = []
    original_replace = Path.replace

    def replace(self: Path, target: Path) -> Path:
        if target == payload_path:
            seen_temp_names.append(self.name)
            if len(seen_temp_names) == 1:
                first_replace_started.set()
                assert release_first_replace.wait(timeout=2)
            else:
                release_first_replace.set()
        return original_replace(self, target)

    monkeypatch.setattr(Path, "replace", replace, raising=False)

    def writer(content: str) -> None:
        try:
            write_text_atomic(payload_path, content)
        except BaseException as exc:  # pragma: no cover - captured for assertion
            errors.append(exc)

    first = threading.Thread(target=writer, args=("alpha",))
    second = threading.Thread(target=writer, args=("bravo",))

    first.start()
    assert first_replace_started.wait(timeout=2)
    second.start()
    first.join(timeout=2)
    second.join(timeout=2)

    assert not first.is_alive()
    assert not second.is_alive()
    assert errors == []
    assert len(seen_temp_names) == 2
    assert len(set(seen_temp_names)) == 2
    assert payload_path.read_text(encoding="utf-8") in {"alpha", "bravo"}
    assert not list(tmp_path.glob("*.tmp"))

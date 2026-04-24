from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "apply_tuning_proposal.py"
TIERING_PATH = Path(__file__).resolve().parents[1] / "src" / "screener" / "scoring" / "tiering.py"


def _make_proposal(tmp_path: Path, proposed: dict | None = None, status: str = "proposal") -> Path:
    if proposed is None:
        proposed = {"min_score": 55, "min_reversal": 12, "min_volume_ratio": 0.8, "max_risk_count": 3}
    payload = {
        "status": status,
        "source": "walk_forward",
        "horizon": 10,
        "generated_at": "2026-04-24T00:00:00+00:00",
        "proposed": proposed,
        "current": {"min_score": 60, "min_reversal": 15, "min_volume_ratio": 0.8, "max_risk_count": 3},
        "diff": {},
    }
    path = tmp_path / "tuning-proposal.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _run_script(proposal_path: Path, extra_args: list[str] | None = None) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(SCRIPT), str(proposal_path)] + (extra_args or [])
    return subprocess.run(cmd, capture_output=True, text=True)


# --- dry-run behaviour ---

def test_dry_run_exits_zero(tmp_path: Path) -> None:
    proposal = _make_proposal(tmp_path)
    result = _run_script(proposal)
    assert result.returncode == 0


def test_dry_run_does_not_modify_tiering_py(tmp_path: Path) -> None:
    original = TIERING_PATH.read_text(encoding="utf-8")
    proposal = _make_proposal(tmp_path)
    _run_script(proposal)
    assert TIERING_PATH.read_text(encoding="utf-8") == original


def test_dry_run_prints_diff(tmp_path: Path) -> None:
    proposal = _make_proposal(tmp_path)
    result = _run_script(proposal)
    assert "min_score" in result.stdout
    assert "YES" in result.stdout


def test_dry_run_reports_unchanged_params(tmp_path: Path) -> None:
    # min_volume_ratio and max_risk_count match current values
    proposal = _make_proposal(tmp_path)
    result = _run_script(proposal)
    assert result.stdout.count("-") >= 2  # two unchanged rows show "-"


# --- no_proposal status ---

def test_no_proposal_status_exits_nonzero(tmp_path: Path) -> None:
    proposal = _make_proposal(tmp_path, status="no_proposal")
    result = _run_script(proposal)
    assert result.returncode != 0
    assert "no_proposal" in result.stdout or "no_proposal" in result.stderr


# --- missing file ---

def test_missing_proposal_file_exits_nonzero(tmp_path: Path) -> None:
    result = _run_script(tmp_path / "nonexistent.json")
    assert result.returncode != 0


# --- apply_to_content unit tests (import directly) ---

def test_apply_to_content_replaces_only_target_lines() -> None:
    import importlib.util
    spec = importlib.util.spec_from_file_location("apply_tuning_proposal", SCRIPT)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]

    original = TIERING_PATH.read_text(encoding="utf-8")
    proposed = {"min_score": 55, "min_reversal": 12, "min_volume_ratio": 1.0, "max_risk_count": 4}
    updated = mod.apply_to_content(original, proposed)

    assert "BUY_REVIEW_MIN_SCORE = 55" in updated
    assert "BUY_REVIEW_MIN_REVERSAL = 12" in updated
    assert "BUY_REVIEW_MIN_VOLUME_RATIO = 1.0" in updated
    assert "BUY_REVIEW_MAX_RISK_COUNT = 4" in updated
    # unchanged lines still present
    assert "BUY_REVIEW_TIER = " in updated
    assert "WATCHLIST_TIER = " in updated
    assert "class TierThresholds" in updated
    # original values gone
    assert "BUY_REVIEW_MIN_SCORE = 60" not in updated


def test_apply_to_content_is_idempotent() -> None:
    import importlib.util
    spec = importlib.util.spec_from_file_location("apply_tuning_proposal", SCRIPT)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]

    original = TIERING_PATH.read_text(encoding="utf-8")
    proposed = {"min_score": 55, "min_reversal": 12, "min_volume_ratio": 0.8, "max_risk_count": 3}
    once = mod.apply_to_content(original, proposed)
    twice = mod.apply_to_content(once, proposed)
    assert once == twice


def test_parse_current_from_file_reads_actual_constants() -> None:
    import importlib.util
    spec = importlib.util.spec_from_file_location("apply_tuning_proposal", SCRIPT)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]

    from screener.scoring.tiering import (
        BUY_REVIEW_MAX_RISK_COUNT,
        BUY_REVIEW_MIN_REVERSAL,
        BUY_REVIEW_MIN_SCORE,
        BUY_REVIEW_MIN_VOLUME_RATIO,
    )

    current = mod.parse_current_from_file(TIERING_PATH)
    assert current["min_score"] == BUY_REVIEW_MIN_SCORE
    assert current["min_reversal"] == BUY_REVIEW_MIN_REVERSAL
    assert current["min_volume_ratio"] == BUY_REVIEW_MIN_VOLUME_RATIO
    assert current["max_risk_count"] == BUY_REVIEW_MAX_RISK_COUNT

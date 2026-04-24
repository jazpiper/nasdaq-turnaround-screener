from __future__ import annotations

import csv
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path

from screener.scoring import TierThresholds
from screener.scoring.tiering import (
    BUY_REVIEW_MAX_RISK_COUNT,
    BUY_REVIEW_MIN_REVERSAL,
    BUY_REVIEW_MIN_SCORE,
    BUY_REVIEW_MIN_VOLUME_RATIO,
)
from screener.storage.files import write_json, write_text

from .runner import GridResult


def write_grid_csv(path: Path, result: GridResult) -> Path:
    """Write all grid combinations and their objective scores to CSV."""
    buf = StringIO()
    fieldnames = [
        "min_score",
        "min_reversal",
        "min_volume_ratio",
        "max_risk_count",
        "excess_return",
        "sample_count",
        "is_valid",
    ]
    writer = csv.DictWriter(buf, fieldnames=fieldnames)
    writer.writeheader()
    for score in result.scores:
        writer.writerow(
            {
                "min_score": score.thresholds.min_score,
                "min_reversal": score.thresholds.min_reversal,
                "min_volume_ratio": score.thresholds.min_volume_ratio,
                "max_risk_count": score.thresholds.max_risk_count,
                "excess_return": score.excess_return,
                "sample_count": score.sample_count,
                "is_valid": score.is_valid,
            }
        )
    return write_text(path, buf.getvalue())


def write_proposal_json(
    path: Path,
    result: GridResult,
    generated_at: datetime | None = None,
) -> Path:
    """Write the best combination as a proposal JSON artifact.

    Includes diff vs current module-level defaults so reviewers can quickly
    assess what would change.
    """
    current = TierThresholds()
    best = result.best
    if best is None:
        payload: dict = {
            "status": "no_proposal",
            "reason": "no grid combination met the minimum sample threshold",
            "horizon": result.horizon,
            "generated_at": (generated_at or datetime.now(timezone.utc)).isoformat(),
            "current": _thresholds_dict(current),
        }
        return write_json(path, payload)

    proposed = best.thresholds
    diff = _build_diff(current, proposed)
    payload = {
        "status": "proposal",
        "horizon": result.horizon,
        "generated_at": (generated_at or datetime.now(timezone.utc)).isoformat(),
        "proposed": _thresholds_dict(proposed),
        "current": _thresholds_dict(current),
        "diff": diff,
        "objective": {
            "excess_return_pct": best.excess_return,
            "sample_count": best.sample_count,
        },
        "current_objective": None,  # populated by apply_tuning_proposal.py after review
    }
    return write_json(path, payload)


def write_diff_markdown(path: Path, result: GridResult) -> Path:
    """Write a human-readable diff of proposed vs current thresholds."""
    current = TierThresholds()
    best = result.best

    lines = ["# Tuning Proposal Diff\n"]
    lines.append(f"**Horizon**: T+{result.horizon}\n")

    if best is None:
        lines.append("**Status**: no proposal — no combination met the minimum sample threshold.\n")
        return write_text(path, "\n".join(lines))

    lines.append(f"**Status**: proposal\n")
    lines.append(f"**Excess return**: {best.excess_return:+.4f}%  |  Sample count: {best.sample_count}\n")
    lines.append("\n## Parameter Changes\n")
    lines.append("| Parameter | Current | Proposed | Changed |")
    lines.append("|---|---|---|---|")

    diff = _build_diff(current, best.thresholds)
    for param, entry in diff.items():
        changed = "**yes**" if entry["changed"] else "no"
        lines.append(f"| {param} | {entry['current']} | {entry['proposed']} | {changed} |")

    lines.append("\n## Review Checklist\n")
    lines.append("- [ ] Reviewed `output/tuning/.../tuning-grid.csv` for runner-up combinations")
    lines.append("- [ ] Checked that sample counts are large enough to be statistically meaningful")
    lines.append("- [ ] Approved changes to `src/screener/scoring/tiering.py`")

    return write_text(path, "\n".join(lines))


def _thresholds_dict(t: TierThresholds) -> dict:
    return {
        "min_score": t.min_score,
        "min_reversal": t.min_reversal,
        "min_volume_ratio": t.min_volume_ratio,
        "max_risk_count": t.max_risk_count,
    }


def _build_diff(current: TierThresholds, proposed: TierThresholds) -> dict:
    fields = [
        ("min_score", current.min_score, proposed.min_score),
        ("min_reversal", current.min_reversal, proposed.min_reversal),
        ("min_volume_ratio", current.min_volume_ratio, proposed.min_volume_ratio),
        ("max_risk_count", current.max_risk_count, proposed.max_risk_count),
    ]
    return {
        name: {"current": cur, "proposed": prop, "changed": cur != prop}
        for name, cur, prop in fields
    }

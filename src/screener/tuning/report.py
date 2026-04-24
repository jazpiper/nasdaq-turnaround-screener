from __future__ import annotations

import csv
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from typing import TYPE_CHECKING

from screener.scoring import TierThresholds
from screener.scoring.tiering import (
    BUY_REVIEW_MAX_RISK_COUNT,
    BUY_REVIEW_MIN_REVERSAL,
    BUY_REVIEW_MIN_SCORE,
    BUY_REVIEW_MIN_VOLUME_RATIO,
)
from screener.storage.files import write_json, write_text

from .runner import GridResult

if TYPE_CHECKING:
    from .walkforward import WalkForwardResult


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


def write_walkforward_json(
    path: Path,
    result: WalkForwardResult,
    generated_at: datetime | None = None,
) -> Path:
    """Write walk-forward summary: per-window bests + stability ranking."""
    current = TierThresholds()
    ts = (generated_at or datetime.now(timezone.utc)).isoformat()

    windows_payload = []
    for w in result.windows:
        windows_payload.append(
            {
                "window_index": w.window_index,
                "train_start": w.train_start.isoformat(),
                "train_end": w.train_end.isoformat(),
                "eval_start": w.eval_start.isoformat(),
                "eval_end": w.eval_end.isoformat(),
                "train_obs_count": w.train_obs_count,
                "eval_obs_count": w.eval_obs_count,
                "best_thresholds": _thresholds_dict(w.best_thresholds) if w.best_thresholds else None,
                "best_train_excess_return": w.best_train_score.excess_return if w.best_train_score else None,
                "best_train_sample_count": w.best_train_score.sample_count if w.best_train_score else None,
                "eval_excess_return": w.eval_score.excess_return if w.eval_score else None,
                "eval_sample_count": w.eval_score.sample_count if w.eval_score else None,
            }
        )

    stability_payload = [
        {
            "thresholds": _thresholds_dict(s.thresholds),
            "win_count": s.win_count,
            "window_indices": s.window_indices,
            "avg_eval_excess_return": s.avg_eval_excess_return,
        }
        for s in result.stability
    ]

    payload = {
        "generated_at": ts,
        "horizon": result.horizon,
        "train_days": result.train_days,
        "eval_days": result.eval_days,
        "stride": result.stride,
        "min_wins": result.min_wins,
        "window_count": len(result.windows),
        "proposal": _thresholds_dict(result.proposal) if result.proposal else None,
        "proposal_status": "proposal" if result.proposal else "no_proposal",
        "current": _thresholds_dict(current),
        "stability": stability_payload,
        "windows": windows_payload,
    }
    return write_json(path, payload)


def write_proposal_json_from_walkforward(
    path: Path,
    result: WalkForwardResult,
    generated_at: datetime | None = None,
) -> Path:
    """Write proposal JSON sourced from a walk-forward result."""
    current = TierThresholds()
    ts = (generated_at or datetime.now(timezone.utc)).isoformat()

    if result.proposal is None:
        payload: dict = {
            "status": "no_proposal",
            "reason": f"no combination won >= {result.min_wins} walk-forward windows",
            "horizon": result.horizon,
            "generated_at": ts,
            "current": _thresholds_dict(current),
            "walk_forward_window_count": len(result.windows),
        }
        return write_json(path, payload)

    proposed = result.proposal
    best_stability = next(s for s in result.stability if s.thresholds == proposed)
    diff = _build_diff(current, proposed)

    payload = {
        "status": "proposal",
        "source": "walk_forward",
        "horizon": result.horizon,
        "generated_at": ts,
        "proposed": _thresholds_dict(proposed),
        "current": _thresholds_dict(current),
        "diff": diff,
        "stability": {
            "win_count": best_stability.win_count,
            "walk_forward_window_count": len(result.windows),
            "avg_eval_excess_return_pct": best_stability.avg_eval_excess_return,
            "window_indices": best_stability.window_indices,
        },
        "current_objective": None,
    }
    return write_json(path, payload)


def write_diff_markdown_from_walkforward(path: Path, result: WalkForwardResult) -> Path:
    """Write a human-readable diff sourced from a walk-forward result."""
    current = TierThresholds()
    lines = ["# Tuning Proposal Diff (Walk-Forward)\n"]
    lines.append(f"**Horizon**: T+{result.horizon}  |  **Windows**: {len(result.windows)}\n")

    if result.proposal is None:
        lines.append(
            f"**Status**: no proposal — no combination won >= {result.min_wins} walk-forward windows.\n"
        )
        return write_text(path, "\n".join(lines))

    best_stability = next(s for s in result.stability if s.thresholds == result.proposal)
    lines.append("**Status**: proposal\n")
    lines.append(
        f"**Win count**: {best_stability.win_count}/{len(result.windows)}  |  "
        f"**Avg out-of-sample excess return**: "
        f"{best_stability.avg_eval_excess_return:+.4f}% "
        if best_stability.avg_eval_excess_return is not None
        else "**Avg out-of-sample excess return**: n/a\n"
    )

    lines.append("\n## Parameter Changes\n")
    lines.append("| Parameter | Current | Proposed | Changed |")
    lines.append("|---|---|---|---|")
    for param, entry in _build_diff(current, result.proposal).items():
        changed = "**yes**" if entry["changed"] else "no"
        lines.append(f"| {param} | {entry['current']} | {entry['proposed']} | {changed} |")

    lines.append("\n## Walk-Forward Window Summary\n")
    lines.append("| Window | Train | Eval | Train Best ER% | OOS ER% |")
    lines.append("|---|---|---|---|---|")
    for w in result.windows:
        train_er = f"{w.best_train_score.excess_return:+.2f}" if w.best_train_score and w.best_train_score.excess_return is not None else "n/a"
        oos_er = f"{w.eval_score.excess_return:+.2f}" if w.eval_score and w.eval_score.excess_return is not None else "n/a"
        lines.append(
            f"| {w.window_index} | {w.train_start} → {w.train_end} | {w.eval_start} → {w.eval_end} | {train_er} | {oos_er} |"
        )

    lines.append("\n## Review Checklist\n")
    lines.append("- [ ] Reviewed `tuning-walkforward.json` for per-window breakdown")
    lines.append("- [ ] Verified out-of-sample excess returns are positive")
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

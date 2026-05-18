from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from screener.storage.files import write_json, write_text

DEFAULT_BACKTEST_SUMMARY_PATH = Path("output/backtests/backtest-summary.json")
DEFAULT_TUNING_PROPOSAL_PATH = Path("output/tuning/2026-04-21/tuning-proposal.json")
DEFAULT_TUNING_WALKFORWARD_PATH = Path("output/tuning-walkforward-6mo-30d/2026-04-21/tuning-walkforward.json")
DEFAULT_DASHBOARD_OUTPUT_DIR = Path("output/performance-dashboard")
DEFAULT_DASHBOARD_JSON_NAME = "performance-dashboard.json"
DEFAULT_DASHBOARD_MARKDOWN_NAME = "performance-dashboard.md"


def load_json_artifact(path: Path, *, required: bool = False) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        if required:
            raise
        return None


def build_performance_dashboard_payload(
    backtest_summary: dict[str, Any],
    *,
    generated_at: datetime,
    backtest_summary_path: Path,
    tuning_proposal: dict[str, Any] | None = None,
    tuning_walkforward: dict[str, Any] | None = None,
    tuning_proposal_path: Path | None = None,
    tuning_walkforward_path: Path | None = None,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    forward_summary = _summarize_forward_return_summary(backtest_summary.get("forward_return_summary", {}))
    tier_summary = _summarize_tier_forward_return_summary(backtest_summary.get("tier_forward_return_summary", {}))
    backtest_highlights = _build_backtest_highlights(backtest_summary, forward_summary, tier_summary)
    tuning_summary = _build_tuning_summary(tuning_proposal, tuning_walkforward)

    payload: dict[str, Any] = {
        "schema_version": 1,
        "generated_at": generated_at.isoformat(),
        "output_dir": str(output_dir) if output_dir is not None else None,
        "source_paths": {
            "backtest_summary_path": str(backtest_summary_path),
            "tuning_proposal_path": str(tuning_proposal_path) if tuning_proposal_path is not None else None,
            "tuning_walkforward_path": str(tuning_walkforward_path) if tuning_walkforward_path is not None else None,
        },
        "backtest": {
            "available": True,
            "status": "available",
            "start_date": backtest_summary.get("start_date"),
            "end_date": backtest_summary.get("end_date"),
            "trading_day_count": backtest_summary.get("trading_day_count"),
            "candidate_observation_count": backtest_summary.get("candidate_observation_count"),
            "forward_horizons": list(backtest_summary.get("forward_horizons", [])),
            "forward_return_summary": forward_summary,
            "tier_forward_return_summary": tier_summary,
            "highlights": backtest_highlights,
        },
        "tuning": tuning_summary,
    }
    return payload


def build_performance_dashboard_markdown(payload: dict[str, Any]) -> str:
    backtest = dict(payload.get("backtest", {}))
    tuning = dict(payload.get("tuning", {}))
    source_paths = dict(payload.get("source_paths", {}))

    lines = [
        "# NASDAQ Turnaround Screener Performance Dashboard",
        "",
        f"- **Generated at**: {payload.get('generated_at')}",
        f"- **Source backtest summary**: {source_paths.get('backtest_summary_path') or 'n/a'}",
        f"- **Source tuning proposal**: {source_paths.get('tuning_proposal_path') or 'n/a'}",
        f"- **Source walk-forward**: {source_paths.get('tuning_walkforward_path') or 'n/a'}",
        "",
        "## Snapshot",
    ]

    for key, label in (
        ("start_date", "Start date"),
        ("end_date", "End date"),
        ("trading_day_count", "Trading days"),
        ("candidate_observation_count", "Candidate observations"),
    ):
        lines.append(f"- **{label}**: {backtest.get(key, 'n/a')}")

    lines.append("")
    lines.append("## Backtest highlights")
    highlights = list(backtest.get("highlights", []))
    if highlights:
        lines.extend(f"- {item}" for item in highlights)
    else:
        lines.append("- No backtest highlights available.")

    lines.append("")
    lines.append("## Forward return summary")
    if backtest.get("forward_return_summary"):
        lines.append("| Horizon | Count | Avg return | Avg excess vs QQQ | Win rate |")
        lines.append("|---|---:|---:|---:|---:|")
        for row in backtest["forward_return_summary"]:
            lines.append(
                f"| {row['horizon']} | {row.get('count', 'n/a')} | {_format_pct(row.get('average_return_pct'))} | "
                f"{_format_pct(row.get('average_excess_return_pct'))} | {_format_rate(row.get('win_rate'))} |"
            )
    else:
        lines.append("- No forward return summary available.")

    lines.append("")
    lines.append("## Tier summary")
    if backtest.get("tier_forward_return_summary"):
        lines.append("| Tier | Horizon | Count | Avg return | Avg excess vs QQQ | Win rate |")
        lines.append("|---|---|---:|---:|---:|---:|")
        for row in backtest["tier_forward_return_summary"]:
            lines.append(
                f"| {row['tier']} | {row['horizon']} | {row.get('count', 'n/a')} | {_format_pct(row.get('average_return_pct'))} | "
                f"{_format_pct(row.get('average_excess_return_pct'))} | {_format_rate(row.get('win_rate'))} |"
            )
    else:
        lines.append("- No tier summary available.")

    lines.append("")
    lines.append("## Tuning status")
    lines.append(f"- **Status**: {tuning.get('status', 'missing')}")
    if tuning.get("highlights"):
        lines.extend(f"- {item}" for item in tuning["highlights"])
    else:
        lines.append("- No tuning artifacts available.")

    proposal = tuning.get("proposal")
    if isinstance(proposal, dict):
        lines.append("")
        lines.append("### Proposal")
        lines.append(f"- **Proposal status**: {proposal.get('status', 'missing')}")
        if proposal.get("horizon") is not None:
            lines.append(f"- **Horizon**: T+{proposal['horizon']}")
        if proposal.get("reason"):
            lines.append(f"- **Reason**: {proposal['reason']}")
        if proposal.get("proposed"):
            lines.append(
                "- **Proposed thresholds**: "
                f"min_score={proposal['proposed'].get('min_score', 'n/a')}, "
                f"min_reversal={proposal['proposed'].get('min_reversal', 'n/a')}, "
                f"min_volume_ratio={proposal['proposed'].get('min_volume_ratio', 'n/a')}, "
                f"max_risk_count={proposal['proposed'].get('max_risk_count', 'n/a')}"
            )
        if proposal.get("objective"):
            objective = proposal["objective"]
            lines.append(
                "- **Objective**: "
                f"excess_return_pct={_format_pct(objective.get('excess_return_pct'))}, "
                f"sample_count={objective.get('sample_count', 'n/a')}"
            )
        if proposal.get("stability"):
            stability = proposal["stability"]
            lines.append(
                "- **Stability**: "
                f"wins={stability.get('win_count', 'n/a')}/{stability.get('walk_forward_window_count', 'n/a')}, "
                f"avg_oos_excess_return_pct={_format_pct(stability.get('avg_eval_excess_return_pct'))}"
            )

    walkforward = tuning.get("walkforward")
    if isinstance(walkforward, dict):
        lines.append("")
        lines.append("### Walk-forward summary")
        lines.append(f"- **Proposal status**: {walkforward.get('proposal_status', 'missing')}")
        if walkforward.get("window_count") is not None:
            lines.append(f"- **Windows**: {walkforward['window_count']}")
        if walkforward.get("proposal"):
            proposed = walkforward["proposal"]
            lines.append(
                "- **Walk-forward proposal**: "
                f"min_score={proposed.get('min_score', 'n/a')}, "
                f"min_reversal={proposed.get('min_reversal', 'n/a')}, "
                f"min_volume_ratio={proposed.get('min_volume_ratio', 'n/a')}, "
                f"max_risk_count={proposed.get('max_risk_count', 'n/a')}"
            )
        if walkforward.get("stability"):
            top_stability = walkforward["stability"][0]
            lines.append(
                "- **Top stability row**: "
                f"wins={top_stability.get('win_count', 'n/a')}, "
                f"valid_eval={top_stability.get('valid_eval_count', 'n/a')}, "
                f"avg_eval_excess_return_pct={_format_pct(top_stability.get('avg_eval_excess_return'))}"
            )

    return "\n".join(lines) + "\n"


def write_performance_dashboard(
    payload: dict[str, Any],
    markdown: str,
    output_dir: Path,
    *,
    artifact_basename: str = "performance-dashboard",
) -> tuple[Path, Path]:
    if not artifact_basename.strip():
        raise ValueError("artifact basename cannot be blank")
    json_path = write_json(output_dir / f"{artifact_basename}.json", payload)
    markdown_path = write_text(output_dir / f"{artifact_basename}.md", markdown)
    return json_path, markdown_path


def load_and_build_performance_dashboard(
    *,
    backtest_summary_path: Path,
    output_dir: Path,
    tuning_proposal_path: Path | None = None,
    tuning_walkforward_path: Path | None = None,
    generated_at: datetime | None = None,
) -> tuple[dict[str, Any], str]:
    backtest_summary = load_json_artifact(backtest_summary_path, required=True)
    if backtest_summary is None:  # pragma: no cover - required=True guarantees a return
        raise FileNotFoundError(backtest_summary_path)

    tuning_proposal = load_json_artifact(tuning_proposal_path) if tuning_proposal_path is not None else None
    tuning_walkforward = load_json_artifact(tuning_walkforward_path) if tuning_walkforward_path is not None else None
    payload = build_performance_dashboard_payload(
        backtest_summary,
        generated_at=generated_at or datetime.now(timezone.utc),
        backtest_summary_path=backtest_summary_path,
        tuning_proposal=tuning_proposal,
        tuning_walkforward=tuning_walkforward,
        tuning_proposal_path=tuning_proposal_path,
        tuning_walkforward_path=tuning_walkforward_path,
        output_dir=output_dir,
    )
    markdown = build_performance_dashboard_markdown(payload)
    return payload, markdown


def _summarize_forward_return_summary(summary: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for horizon_key, metrics in sorted(summary.items(), key=lambda item: _horizon_sort_key(item[0])):
        row: dict[str, Any] = {"horizon": horizon_key}
        if isinstance(metrics, dict):
            row["count"] = metrics.get("count")
            row["average_return_pct"] = metrics.get("average_return_pct")
            row["average_excess_return_pct"] = metrics.get("average_excess_return_pct")
            row["win_rate"] = metrics.get("win_rate")
            row["median_return_pct"] = metrics.get("median_return_pct")
            row["excess_count"] = metrics.get("excess_count")
        rows.append(row)
    return rows


def _summarize_tier_forward_return_summary(summary: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for tier, horizons in summary.items():
        if not isinstance(horizons, dict):
            continue
        for horizon_key, metrics in sorted(horizons.items(), key=lambda item: _horizon_sort_key(item[0])):
            row: dict[str, Any] = {"tier": tier, "horizon": horizon_key}
            if isinstance(metrics, dict):
                row["count"] = metrics.get("count")
                row["average_return_pct"] = metrics.get("average_return_pct")
                row["average_excess_return_pct"] = metrics.get("average_excess_return_pct")
                row["win_rate"] = metrics.get("win_rate")
                row["median_return_pct"] = metrics.get("median_return_pct")
                row["excess_count"] = metrics.get("excess_count")
            rows.append(row)
    return rows


def _build_backtest_highlights(
    backtest_summary: dict[str, Any],
    forward_rows: list[dict[str, Any]],
    tier_rows: list[dict[str, Any]],
) -> list[str]:
    highlights: list[str] = []
    trading_days = backtest_summary.get("trading_day_count")
    observation_count = backtest_summary.get("candidate_observation_count")
    if trading_days is not None or observation_count is not None:
        highlights.append(
            f"Backtest covers {trading_days if trading_days is not None else 'n/a'} trading days and "
            f"{observation_count if observation_count is not None else 'n/a'} candidate observations."
        )

    ten_day_row = next((row for row in forward_rows if row.get("horizon") == "10d"), None)
    if ten_day_row is not None:
        highlights.append(
            "10d forward return: "
            f"{_format_pct(ten_day_row.get('average_return_pct'))} average, "
            f"{_format_pct(ten_day_row.get('average_excess_return_pct'))} excess vs QQQ, "
            f"{_format_rate(ten_day_row.get('win_rate'))} win rate."
        )

    if tier_rows:
        best_tier = max(
            tier_rows,
            key=lambda row: (
                _numeric_or_negative_inf(row.get("average_excess_return_pct")),
                _numeric_or_negative_inf(row.get("win_rate")),
            ),
        )
        highlights.append(
            f"Best tier snapshot: {best_tier['tier']} / {best_tier['horizon']} "
            f"with {_format_pct(best_tier.get('average_excess_return_pct'))} excess and "
            f"{_format_rate(best_tier.get('win_rate'))} win rate."
        )

    return highlights


def _build_tuning_summary(
    tuning_proposal: dict[str, Any] | None,
    tuning_walkforward: dict[str, Any] | None,
) -> dict[str, Any]:
    proposal_summary: dict[str, Any] | None = None
    walkforward_summary: dict[str, Any] | None = None
    highlights: list[str] = []

    if tuning_proposal is not None:
        proposal_summary = {
            "status": tuning_proposal.get("status", "missing"),
            "source": tuning_proposal.get("source"),
            "horizon": tuning_proposal.get("horizon"),
            "reason": tuning_proposal.get("reason"),
            "proposed": tuning_proposal.get("proposed"),
            "current": tuning_proposal.get("current"),
            "objective": tuning_proposal.get("objective"),
            "stability": tuning_proposal.get("stability"),
        }
        if tuning_proposal.get("status") == "proposal":
            proposed = tuning_proposal.get("proposed", {})
            objective = tuning_proposal.get("objective", {})
            highlights.append(
                "Tuning proposal available: "
                f"min_score={proposed.get('min_score', 'n/a')}, "
                f"min_reversal={proposed.get('min_reversal', 'n/a')}, "
                f"min_volume_ratio={proposed.get('min_volume_ratio', 'n/a')}, "
                f"max_risk_count={proposed.get('max_risk_count', 'n/a')}, "
                f"excess_return={_format_pct(objective.get('excess_return_pct'))}."
            )
        else:
            highlights.append(f"Tuning proposal unavailable: {tuning_proposal.get('reason', 'no proposal')}")

    if tuning_walkforward is not None:
        walkforward_summary = {
            "status": tuning_walkforward.get("proposal_status", "missing"),
            "window_count": tuning_walkforward.get("window_count"),
            "horizon": tuning_walkforward.get("horizon"),
            "proposal": tuning_walkforward.get("proposal"),
            "stability": tuning_walkforward.get("stability"),
        }
        if tuning_walkforward.get("proposal") is not None:
            proposal = tuning_walkforward["proposal"]
            highlights.append(
                "Walk-forward proposal: "
                f"min_score={proposal.get('min_score', 'n/a')}, "
                f"min_reversal={proposal.get('min_reversal', 'n/a')}, "
                f"min_volume_ratio={proposal.get('min_volume_ratio', 'n/a')}, "
                f"max_risk_count={proposal.get('max_risk_count', 'n/a')}."
            )
        if tuning_walkforward.get("stability"):
            top_stability = tuning_walkforward["stability"][0]
            highlights.append(
                "Walk-forward stability leader: "
                f"wins={top_stability.get('win_count', 'n/a')}/"
                f"{tuning_walkforward.get('window_count', 'n/a')}, "
                f"avg OOS excess={_format_pct(top_stability.get('avg_eval_excess_return'))}."
            )
        elif tuning_walkforward.get("proposal_status"):
            highlights.append(f"Walk-forward status: {tuning_walkforward.get('proposal_status')}")

    if not highlights:
        highlights.append("No tuning artifacts found.")

    return {
        "available": tuning_proposal is not None or tuning_walkforward is not None,
        "status": "available" if tuning_proposal is not None or tuning_walkforward is not None else "missing",
        "highlights": highlights,
        "proposal": proposal_summary,
        "walkforward": walkforward_summary,
    }


def _format_pct(value: Any) -> str:
    if value is None:
        return "n/a"
    try:
        return f"{float(value):+0.2f}%"
    except (TypeError, ValueError):
        return str(value)


def _format_rate(value: Any) -> str:
    if value is None:
        return "n/a"
    try:
        return f"{float(value) * 100:0.1f}%"
    except (TypeError, ValueError):
        return str(value)


def _horizon_sort_key(label: Any) -> int:
    try:
        text = str(label)
        if text.endswith("d"):
            text = text[:-1]
        return int(text)
    except (TypeError, ValueError):
        return 10_000


def _numeric_or_negative_inf(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("-inf")

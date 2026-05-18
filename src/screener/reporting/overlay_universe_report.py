from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from screener.storage.files import write_json, write_text
from screener.universe import DEFAULT_UNIVERSE_NAME, USER_WATCHLIST_UNIVERSE_NAME

DEFAULT_BASELINE_DAILY_REPORT_PATH = Path("output/daily/latest/daily-report.json")
DEFAULT_OVERLAY_DAILY_REPORT_PATH = Path("output/daily-user-watchlist-hot-sector-overlay/2026-05-14/daily-report.json")
DEFAULT_OVERLAY_METADATA_PATH = Path("output/overlays/hot-sector-overlay.json")
DEFAULT_BACKTEST_SUMMARY_PATH = Path("output/backtests/backtest-summary.json")
DEFAULT_REPORT_OUTPUT_DIR = Path("output/overlay-universe-report")
DEFAULT_ARTIFACT_BASENAME = "overlay-universe-report"


def load_json_artifact(path: Path, *, required: bool = False) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        if required:
            raise
        return None


def build_overlay_universe_report_payload(
    baseline_report: dict[str, Any],
    overlay_report: dict[str, Any],
    overlay_metadata: dict[str, Any],
    *,
    generated_at: datetime,
    baseline_report_path: Path,
    overlay_report_path: Path,
    overlay_metadata_path: Path,
    backtest_summary: dict[str, Any] | None = None,
    backtest_summary_path: Path | None = None,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    baseline_candidates = _index_candidates(baseline_report)
    overlay_candidates = _index_candidates(overlay_report)
    baseline_tickers = set(baseline_candidates)
    overlay_tickers = set(overlay_candidates)
    baseline_planned = _normalize_ticker_set(baseline_report.get("planned_tickers", []))
    overlay_planned = _normalize_ticker_set(overlay_report.get("planned_tickers", []))

    payload: dict[str, Any] = {
        "schema_version": 1,
        "generated_at": generated_at.isoformat(),
        "output_dir": str(output_dir) if output_dir is not None else None,
        "source_paths": {
            "baseline_report_path": str(baseline_report_path),
            "overlay_report_path": str(overlay_report_path),
            "overlay_metadata_path": str(overlay_metadata_path),
            "backtest_summary_path": str(backtest_summary_path) if backtest_summary_path is not None else None,
        },
        "comparison": {
            "baseline": _summarize_report(baseline_report, baseline_report_path),
            "overlay": _summarize_report(overlay_report, overlay_report_path),
            "deltas": {
                "planned_ticker_count": _delta_int(overlay_report.get("planned_ticker_count"), baseline_report.get("planned_ticker_count")),
                "candidate_count": _delta_int(overlay_report.get("candidate_count"), baseline_report.get("candidate_count")),
                "planned_ticker_overlap_count": len(baseline_planned & overlay_planned),
                "overlay_added_planned_tickers": sorted(overlay_planned - baseline_planned),
                "overlay_removed_planned_tickers": sorted(baseline_planned - overlay_planned),
                "overlay_only_candidate_tickers": [ticker for ticker in overlay_candidates if ticker not in baseline_tickers],
                "baseline_only_candidate_tickers": [ticker for ticker in baseline_candidates if ticker not in overlay_tickers],
            },
        },
        "overlay": _build_overlay_summary(overlay_metadata),
        "universe_variants": _build_universe_variants(
            baseline_report=baseline_report,
            overlay_report=overlay_report,
            overlay_metadata=overlay_metadata,
            baseline_report_path=baseline_report_path,
            overlay_report_path=overlay_report_path,
            overlay_metadata_path=overlay_metadata_path,
        ),
        "backtest": _build_backtest_context(backtest_summary, backtest_summary_path),
    }
    return payload


def build_overlay_universe_report_markdown(payload: dict[str, Any]) -> str:
    source_paths = dict(payload.get("source_paths", {}))
    comparison = dict(payload.get("comparison", {}))
    baseline = dict(comparison.get("baseline", {}))
    overlay = dict(comparison.get("overlay", {}))
    deltas = dict(comparison.get("deltas", {}))
    overlay_summary = dict(payload.get("overlay", {}))
    backtest = dict(payload.get("backtest", {}))
    variants = list(payload.get("universe_variants", []))

    baseline_candidate_tickers = set(baseline.get('candidate_tickers', []))
    overlay_candidate_tickers = set(overlay.get('candidate_tickers', []))
    candidate_overlap = len(baseline_candidate_tickers & overlay_candidate_tickers)

    lines = [
        "# NASDAQ Turnaround Screener Overlay / Universe Comparison",
        "",
        f"- **Generated at**: {payload.get('generated_at')}",
        f"- **Baseline report**: {source_paths.get('baseline_report_path') or 'n/a'}",
        f"- **Overlay report**: {source_paths.get('overlay_report_path') or 'n/a'}",
        f"- **Overlay metadata**: {source_paths.get('overlay_metadata_path') or 'n/a'}",
        f"- **Backtest summary**: {source_paths.get('backtest_summary_path') or 'n/a'}",
        "",
        "## Comparison",
        "| Metric | Baseline | Overlay | Delta |",
        "|---|---:|---:|---:|",
        f"| Planned tickers | {baseline.get('planned_ticker_count', 'n/a')} | {overlay.get('planned_ticker_count', 'n/a')} | {deltas.get('planned_ticker_count', 'n/a')} |",
        f"| Candidate count | {baseline.get('candidate_count', 'n/a')} | {overlay.get('candidate_count', 'n/a')} | {deltas.get('candidate_count', 'n/a')} |",
        f"| Candidate overlap | {candidate_overlap} | {candidate_overlap} | n/a |",
    ]

    added_planned = list(deltas.get("overlay_added_planned_tickers", []))
    removed_planned = list(deltas.get("overlay_removed_planned_tickers", []))
    if added_planned or removed_planned:
        lines.extend([
            "",
            "### Planned ticker changes",
        ])
        if added_planned:
            lines.append(f"- Added by overlay: {', '.join(added_planned)}")
        if removed_planned:
            lines.append(f"- Removed by overlay: {', '.join(removed_planned)}")

    overlay_only_candidates = list(deltas.get("overlay_only_candidate_tickers", []))
    baseline_only_candidates = list(deltas.get("baseline_only_candidate_tickers", []))
    lines.extend([
        "",
        "## Overlay contribution",
        f"- **Overlay-only candidates**: {len(overlay_only_candidates)}",
        f"- **Baseline-only candidates**: {len(baseline_only_candidates)}",
    ])
    if overlay_only_candidates:
        lines.append(f"- **Overlay-only tickers**: {', '.join(overlay_only_candidates[:12])}")

    selected_sectors = list(overlay_summary.get("selected_sectors", []))
    tickers = list(overlay_summary.get("tickers", []))
    signals = list(overlay_summary.get("signals", []))
    lines.extend([
        "",
        "## Overlay metadata",
        f"- **Selected sectors**: {', '.join(selected_sectors) if selected_sectors else 'n/a'}",
        f"- **Overlay tickers**: {', '.join(tickers) if tickers else 'n/a'}",
    ])
    if signals:
        lines.append("")
        lines.append("| Sector | Proxy | Score | Selected | Excess 20d | Excess 60d |")
        lines.append("|---|---|---:|---|---:|---:|")
        for signal in signals:
            lines.append(
                f"| {signal.get('sector', 'n/a')} | {signal.get('proxy_ticker', 'n/a')} | {signal.get('score', 'n/a')} | "
                f"{_format_bool(signal.get('selected'))} | {_format_number(signal.get('excess_20d'))} | {_format_number(signal.get('excess_60d'))} |"
            )

    lines.extend([
        "",
        "## Universe variants / presets",
    ])
    if variants:
        lines.append("| Variant | Base universe | Overlay | Planned tickers | Candidate count | Notes |")
        lines.append("|---|---|---|---:|---:|---|")
        for variant in variants:
            lines.append(
                f"| {variant.get('variant_id', 'n/a')} | {variant.get('base_universe', 'n/a')} | {variant.get('overlay_name', 'n/a')} | "
                f"{variant.get('planned_ticker_count', 'n/a')} | {variant.get('candidate_count', 'n/a')} | {variant.get('description', '')} |"
            )
    else:
        lines.append("- No universe variants available.")

    lines.extend([
        "",
        "## Backtest context",
    ])
    if backtest.get("available"):
        lines.append(f"- **Trading days**: {backtest.get('trading_day_count', 'n/a')}")
        lines.append(f"- **Candidate observations**: {backtest.get('candidate_observation_count', 'n/a')}")
        if backtest.get("forward_horizons"):
            lines.append(f"- **Horizons**: {', '.join(str(horizon) for horizon in backtest['forward_horizons'])}")
    else:
        lines.append("- No backtest summary available.")

    return "\n".join(lines) + "\n"


def write_overlay_universe_report(
    payload: dict[str, Any],
    markdown: str,
    output_dir: Path,
    *,
    artifact_basename: str = DEFAULT_ARTIFACT_BASENAME,
) -> tuple[Path, Path]:
    if not artifact_basename.strip():
        raise ValueError("artifact basename cannot be blank")
    json_path = write_json(output_dir / f"{artifact_basename}.json", payload)
    markdown_path = write_text(output_dir / f"{artifact_basename}.md", markdown)
    return json_path, markdown_path


def load_and_build_overlay_universe_report(
    *,
    baseline_report_path: Path,
    overlay_report_path: Path,
    overlay_metadata_path: Path,
    output_dir: Path,
    backtest_summary_path: Path | None = None,
    generated_at: datetime | None = None,
) -> tuple[dict[str, Any], str]:
    baseline_report = load_json_artifact(baseline_report_path, required=True)
    overlay_report = load_json_artifact(overlay_report_path, required=True)
    overlay_metadata = load_json_artifact(overlay_metadata_path, required=True)
    if baseline_report is None or overlay_report is None or overlay_metadata is None:  # pragma: no cover - required=True guarantees return
        raise FileNotFoundError("Missing overlay universe report inputs")
    backtest_summary = load_json_artifact(backtest_summary_path) if backtest_summary_path is not None else None
    payload = build_overlay_universe_report_payload(
        baseline_report,
        overlay_report,
        overlay_metadata,
        generated_at=generated_at or datetime.now(timezone.utc),
        baseline_report_path=baseline_report_path,
        overlay_report_path=overlay_report_path,
        overlay_metadata_path=overlay_metadata_path,
        backtest_summary=backtest_summary,
        backtest_summary_path=backtest_summary_path,
        output_dir=output_dir,
    )
    markdown = build_overlay_universe_report_markdown(payload)
    return payload, markdown


def _summarize_report(report: dict[str, Any], report_path: Path) -> dict[str, Any]:
    candidate_tickers = _index_candidates(report)
    return {
        "universe": report.get("universe"),
        "date": report.get("date"),
        "report_path": str(report_path),
        "planned_ticker_count": report.get("planned_ticker_count"),
        "candidate_count": report.get("candidate_count"),
        "candidate_tickers": list(candidate_tickers),
    }


def _build_overlay_summary(overlay_metadata: dict[str, Any]) -> dict[str, Any]:
    signals = []
    for item in overlay_metadata.get("signals", []):
        if not isinstance(item, dict):
            continue
        signals.append(
            {
                "sector": item.get("sector"),
                "proxy_ticker": item.get("proxy_ticker"),
                "selected": bool(item.get("selected")),
                "score": item.get("score"),
                "excess_20d": item.get("excess_20d"),
                "excess_60d": item.get("excess_60d"),
            }
        )
    return {
        "selected_sectors": list(overlay_metadata.get("selected_sectors", [])),
        "tickers": list(overlay_metadata.get("tickers", [])),
        "signal_count": len(signals),
        "signals": signals,
    }


def _build_universe_variants(
    *,
    baseline_report: dict[str, Any],
    overlay_report: dict[str, Any],
    overlay_metadata: dict[str, Any],
    baseline_report_path: Path,
    overlay_report_path: Path,
    overlay_metadata_path: Path,
) -> list[dict[str, Any]]:
    overlay_name = str(overlay_metadata_path.stem or "hot-sector-overlay")
    overlay_universe_name = overlay_report.get("universe") or f"{DEFAULT_UNIVERSE_NAME}+{overlay_name}"
    return [
        {
            "variant_id": "core-nasdaq-100",
            "base_universe": DEFAULT_UNIVERSE_NAME,
            "overlay_name": None,
            "status": "available",
            "planned_ticker_count": baseline_report.get("planned_ticker_count"),
            "candidate_count": baseline_report.get("candidate_count"),
            "source_paths": {"report_path": str(baseline_report_path)},
            "description": "Core NASDAQ-100 only.",
        },
        {
            "variant_id": "nasdaq-100-plus-hot-sector-overlay",
            "base_universe": DEFAULT_UNIVERSE_NAME,
            "overlay_name": overlay_name,
            "status": "available",
            "planned_ticker_count": overlay_report.get("planned_ticker_count"),
            "candidate_count": overlay_report.get("candidate_count"),
            "source_paths": {
                "report_path": str(overlay_report_path),
                "overlay_metadata_path": str(overlay_metadata_path),
            },
            "overlay_universe_name": overlay_universe_name,
            "description": "Current overlay-backed universe example.",
        },
        {
            "variant_id": "user-watchlist-plus-hot-sector-overlay",
            "base_universe": USER_WATCHLIST_UNIVERSE_NAME,
            "overlay_name": overlay_name,
            "status": "template",
            "planned_ticker_count": None,
            "candidate_count": None,
            "source_paths": {"overlay_metadata_path": str(overlay_metadata_path)},
            "overlay_universe_name": f"{USER_WATCHLIST_UNIVERSE_NAME}+{overlay_name}",
            "description": "Future experiment preset for user watchlists combined with the hot-sector overlay.",
        },
    ]


def _build_backtest_context(backtest_summary: dict[str, Any] | None, backtest_summary_path: Path | None) -> dict[str, Any]:
    if not backtest_summary:
        return {
            "available": False,
            "status": "missing",
            "source_path": str(backtest_summary_path) if backtest_summary_path is not None else None,
        }
    return {
        "available": True,
        "status": "available",
        "source_path": str(backtest_summary_path) if backtest_summary_path is not None else None,
        "trading_day_count": backtest_summary.get("trading_day_count"),
        "candidate_observation_count": backtest_summary.get("candidate_observation_count"),
        "forward_horizons": list(backtest_summary.get("forward_horizons", [])),
    }


def _index_candidates(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    candidates: dict[str, dict[str, Any]] = {}
    for item in report.get("candidates", []):
        if not isinstance(item, dict):
            continue
        ticker = item.get("ticker")
        if ticker is None:
            continue
        candidates[str(ticker).upper()] = item
    return candidates


def _normalize_ticker_set(values: Any) -> set[str]:
    normalized: set[str] = set()
    for value in values or []:
        text = str(value).strip().upper()
        if text:
            normalized.add(text)
    return normalized


def _delta_int(overlay_value: Any, baseline_value: Any) -> int | str:
    try:
        return int(overlay_value) - int(baseline_value)
    except (TypeError, ValueError):
        return "n/a"


def _format_number(value: Any) -> str:
    if value is None:
        return "n/a"
    try:
        return f"{float(value):+.2f}"
    except (TypeError, ValueError):
        return str(value)


def _format_bool(value: Any) -> str:
    return "yes" if bool(value) else "no"
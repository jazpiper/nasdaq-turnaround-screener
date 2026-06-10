from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from screener.data.resilience import derive_market_data_reliability_label
from screener.overlay.hot_sector import SECTOR_PROXY_TICKERS
from screener.storage.files import write_json, write_text
from screener.universe import normalize_ticker

JSON_ARTIFACT_NAME = "latest-user-briefing-screener.json"
MARKDOWN_ARTIFACT_NAME = "latest-user-briefing-screener.md"

_REVIEW_STAGE_LABELS = {
    "buy-review": "검토",
    "watchlist": "관심",
    "avoid/high-risk": "보류",
}


def parse_user_tickers(raw: str) -> list[str]:
    return _dedupe_tickers([part.strip() for part in raw.replace("\n", ",").split(",")])


def load_daily_report(report_path: Path) -> dict[str, Any]:
    return json.loads(report_path.read_text(encoding="utf-8"))


def load_user_universe_contract(path: Path) -> dict[str, dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"User universe config must be a JSON object: {path}")

    priority_order = raw.get("coverage_policy", {}).get("priority_order") or [
        "holdings",
        "focus_watchlist",
        "big_tech_p1",
        "big_tech_p2",
    ]
    if not isinstance(priority_order, list):
        raise ValueError(f"coverage_policy.priority_order must be a list: {path}")

    contract: dict[str, dict[str, Any]] = {}
    for priority, lane in enumerate(priority_order):
        lane_name = str(lane).strip()
        if not lane_name:
            continue
        lane_items = raw.get(lane_name, [])
        if lane_name == "holdings":
            tickers = [item.get("ticker") for item in lane_items if isinstance(item, dict)]
        elif isinstance(lane_items, list):
            tickers = lane_items
        else:
            raise ValueError(f"{lane_name} must be a list in user universe config: {path}")

        for ticker in _dedupe_tickers(str(item).strip() for item in tickers if str(item).strip()):
            existing = contract.get(ticker)
            if existing is not None and int(existing.get("priority", 9999)) <= priority:
                continue
            contract[ticker] = {
                "tracking_lane": lane_name,
                "priority": priority,
                "briefing_section": "holdings" if lane_name == "holdings" else "watchlist",
                "briefing_label_family": "holding" if lane_name == "holdings" else "watchlist",
            }

    return contract


def _build_source_contract(
    daily_report: dict[str, Any],
    data_quality: dict[str, Any],
    source_report_path: Path | None,
) -> dict[str, Any]:
    provider_statuses = list(data_quality.get("market_data_provider_status", []))
    if any(status.get("used_stale_cache") for status in provider_statuses):
        freshness = "stale"
    elif any(
        int(data_quality.get(key) or 0) > 0
        for key in ("failed_ticker_count", "latest_bar_date_mismatch_count", "insufficient_history_count")
    ):
        freshness = "partial"
    elif int(data_quality.get("successful_ticker_count") or 0) < int(data_quality.get("planned_ticker_count") or 0):
        freshness = "partial"
    else:
        freshness = "fresh"

    reliability_label = data_quality.get("reliability_label") or daily_report.get("reliability_label") or "unofficial"
    source = str(daily_report.get("source") or "nasdaq-turnaround-screener")
    return {
        "source": source,
        "source_report_path": str(source_report_path) if source_report_path is not None else None,
        "freshness": freshness,
        "reliability_label": reliability_label,
        "market_data_reliability": data_quality.get("market_data_reliability") or reliability_label,
    }


def build_assistant_briefing_payload(
    daily_report: dict[str, Any],
    *,
    user_tickers: list[str],
    top_candidate_count: int = 5,
    generated_at: datetime,
    source_report_path: Path | None = None,
    tracked_ticker_contract: dict[str, dict[str, Any]] | None = None,
    previous_top3_feedback: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data_quality = _build_data_quality(daily_report)
    candidate_rows = list(daily_report.get("candidates", []))
    candidate_by_ticker = {str(row.get("ticker", "")).upper(): row for row in candidate_rows}
    rank_by_ticker = {str(row.get("ticker", "")).upper(): index + 1 for index, row in enumerate(candidate_rows)}
    planned_tickers = {str(ticker).upper() for ticker in daily_report.get("planned_tickers", [])}
    data_failures_by_ticker = _parse_data_failures(daily_report.get("data_failures", []))
    source_contract = _build_source_contract(daily_report, data_quality, source_report_path)
    tracked_contract = tracked_ticker_contract or {}
    ordered_user_tickers = _dedupe_tickers(user_tickers)
    user_universe = set(ordered_user_tickers)

    payload: dict[str, Any] = {
        "schema_version": 2,
        "source": source_contract["source"],
        "generated_at": generated_at.isoformat(),
        "screener_date": daily_report.get("date"),
        "source_report_path": str(source_report_path) if source_report_path is not None else None,
        "source_contract": source_contract,
        "source_freshness": source_contract["freshness"],
        "source_reliability": source_contract["reliability_label"],
        "universe": daily_report.get("universe"),
        "data_quality": data_quality,
        "user_tickers": [],
        "missing_user_tickers": [],
        "top_candidates": [],
        "overlay_candidates": [],
        "previous_top3_feedback": previous_top3_feedback,
        "notes": [
            "Signals are technical/research signals only and not buy/sell advice.",
            "Treat 관심/검토/보류 as review stages only; valuation, business quality, and catalysts still need separate confirmation before any buy decision.",
        ],
    }

    for ticker in ordered_user_tickers:
        item = _build_user_ticker_item(
            ticker,
            planned_tickers,
            candidate_by_ticker,
            rank_by_ticker,
            data_failures_by_ticker,
            daily_report,
            tracked_contract.get(ticker),
        )
        payload["user_tickers"].append(item)
        if not item.get("in_screener_universe"):
            payload["missing_user_tickers"].append({"ticker": ticker, "reason": _missing_reason(ticker)})

    for row in candidate_rows:
        ticker = str(row.get("ticker", "")).upper()
        if ticker in user_universe:
            continue
        candidate = _compact_candidate(
            row,
            rank=rank_by_ticker.get(ticker, 0),
            daily_report=daily_report,
        )
        payload["top_candidates"].append(candidate)
        if len(payload["top_candidates"]) >= max(0, top_candidate_count):
            break

    payload["overlay_candidates"] = [
        candidate for candidate in payload["top_candidates"] if candidate.get("ticker") not in user_universe
    ]

    return payload


def _build_watchlist_section_lines(payload: dict[str, Any]) -> list[str]:
    lines = [
        "## User universe tracking",
        "These are the user’s tracked tickers and are shown separately from discovery candidates.",
        "",
        "### Holdings lane",
    ]
    holdings = [item for item in payload.get("user_tickers", []) if item.get("briefing_section") == "holdings"]
    watchlist = [item for item in payload.get("user_tickers", []) if item.get("briefing_section") != "holdings"]

    if holdings:
        for item in holdings:
            stage = item.get("briefing_label") or item.get("review_stage") or _format_assistant_stage(item)
            summary = f"- **{item['ticker']}**: {stage} | holding lane"
            if item.get("is_candidate"):
                summary += f" | technical candidate rank {item.get('rank')} | score {item.get('score')}"
                provenance = _format_source_provenance(item.get("source_provenance"))
                if provenance:
                    summary += f" | {provenance}"
                sector_context = _format_sector_relative_context(item)
                if sector_context:
                    summary += f" | {sector_context}"
            elif item.get("data_failure"):
                summary += f" | data failure: {item.get('data_failure_reason')}"
            elif not item.get("in_screener_universe"):
                summary += " | outside screener universe"
            lines.append(summary)
            if item.get("briefing_interpretation"):
                lines.append(f"  - {item['briefing_interpretation']}")
            if item.get("review_stage_reason"):
                lines.append(f"  - technical note: {item['review_stage_reason']}")
            if item.get("is_candidate"):
                lines.extend(_format_candidate_explanation_lines(item, indent="  - "))
    else:
        lines.append("- None")

    lines.extend(["", "### Watchlist / basket lane"])
    if not watchlist:
        lines.append("- None")
        return lines

    for item in watchlist:
        stage = item.get("briefing_label") or item.get("review_stage") or _format_assistant_stage(item)
        if item.get("is_candidate"):
            summary = (
                f"- **{item['ticker']}**: {stage} | rank {item.get('rank')} | score {item.get('score')} | "
                f"risk-adjusted {item.get('risk_adjusted_score')}"
            )
            provenance = _format_source_provenance(item.get("source_provenance"))
            if provenance:
                summary += f" | {provenance}"
            sector_context = _format_sector_relative_context(item)
            if sector_context:
                summary += f" | {sector_context}"
            lines.append(summary)
            if item.get("review_stage_reason"):
                lines.append(f"  - {item['review_stage_reason']}")
            lines.extend(_format_candidate_explanation_lines(item, indent="  - "))
        else:
            summary = f"- **{item['ticker']}**: {stage}"
            if item.get("data_failure"):
                summary += f" | data failure: {item.get('data_failure_reason')}"
            elif item.get("review_stage_reason"):
                summary += f" | {item.get('review_stage_reason')}"
            if not item.get("in_screener_universe"):
                summary += " | outside screener universe"
            lines.append(summary)
    return lines


def _build_discovery_section_lines(payload: dict[str, Any]) -> list[str]:
    lines = [
        "## New discovery candidates",
        f"Top {payload.get('universe') or 'source screener universe'} review candidates from the screener output.",
    ]
    top_candidates = payload.get("top_candidates", [])
    if top_candidates:
        for candidate in top_candidates:
            heading = candidate["ticker"]
            if candidate.get("name"):
                heading += f" ({candidate['name']})"
            summary = (
                f"- **#{candidate['rank']} {heading}**: {candidate.get('review_stage') or _review_stage_label(candidate.get('tier'))} | "
                f"score {candidate.get('score')} | risk-adjusted {candidate.get('risk_adjusted_score')}"
            )
            provenance = _format_source_provenance(candidate.get("source_provenance"))
            if provenance:
                summary += f" | {provenance}"
            sector_context = _format_sector_relative_context(candidate)
            if sector_context:
                summary += f" | {sector_context}"
            lines.append(summary)
            lines.extend(_format_candidate_explanation_lines(candidate, indent="  - "))
    else:
        lines.append("- None")
    return lines


def _build_overlay_section_lines(payload: dict[str, Any]) -> list[str]:
    lines = ["## Overlay candidates (outside user universe)"]
    overlay_candidates = payload.get("overlay_candidates", [])
    if overlay_candidates:
        lines.extend(f"- {candidate.get('ticker')}: rank {candidate.get('rank')}" for candidate in overlay_candidates)
    else:
        lines.append("- None")
    return lines


def _build_previous_top3_feedback_section_lines(payload: dict[str, Any]) -> list[str]:
    raw_feedback = payload.get("previous_top3_feedback")
    if not isinstance(raw_feedback, dict):
        return []

    feedback = dict(raw_feedback)
    lines = ["## Previous Top3 outcome feedback"]
    if not feedback.get("available"):
        source_run_date = feedback.get("source_run_date")
        horizon_label = feedback.get("horizon_label") or "D+1"
        reason = feedback.get("reason") or "unavailable"
        prefix = f"Latest prior Top3 run {source_run_date} {horizon_label}" if source_run_date else f"Latest prior Top3 {horizon_label}"
        lines.append(f"- {prefix}: unavailable ({reason})")
        return lines

    source_run_date = feedback.get("source_run_date") or "unknown"
    horizon_label = feedback.get("horizon_label") or "D+1"
    lines.append(
        f"- Run date {source_run_date} | horizon {horizon_label} | filled {feedback.get('filled_count', 0)} | "
        f"no-fill {feedback.get('no_fill_count', 0)} | negative {feedback.get('negative_return_count', 0)}"
    )
    for item in feedback.get("items", []):
        if not isinstance(item, dict):
            continue
        heading = f"#{item.get('rank')} {item.get('ticker')}"
        if item.get("name"):
            heading += f" ({item['name']})"
        status = "체결" if item.get("fill_status") == "filled" else "미체결"
        summary = f"- **{heading}**: {status}"
        absolute_return_pct = item.get("absolute_return_pct")
        if absolute_return_pct is not None:
            summary += f" | return {float(absolute_return_pct):+.2f}%"
        relative_return_vs_spy_pct = item.get("relative_return_vs_spy_pct")
        if relative_return_vs_spy_pct is not None:
            summary += f" | vs SPY {float(relative_return_vs_spy_pct):+.2f}%"
        if item.get("exit_reason"):
            summary += f" | exit {item['exit_reason']}"
        if item.get("warning_flags"):
            summary += f" | warning {', '.join(str(flag) for flag in item['warning_flags'])}"
        elif item.get("observation_note"):
            summary += f" | note {item['observation_note']}"
        lines.append(summary)
    return lines


def _build_consumer_messaging_section_lines(payload: dict[str, Any]) -> list[str]:
    lines = ["## Notes"]
    lines.extend(f"- {note}" for note in payload.get("notes", []))
    return lines


def _build_missing_tickers_section_lines(payload: dict[str, Any]) -> list[str]:
    lines = ["## Missing tickers / outside universe"]
    missing_items = payload.get("missing_user_tickers", [])
    if missing_items:
        lines.extend(f"- {item['ticker']}: {item['reason']}" for item in missing_items)
    else:
        lines.append("- None")
    return lines


def build_assistant_briefing_markdown(payload: dict[str, Any]) -> str:
    lines = [
        f"# NASDAQ Screener Assistant Briefing ({payload.get('screener_date')})",
        "",
        "These signals are decision-support only and not buy/sell advice.",
        "",
        "## Source / freshness / reliability",
    ]
    source_contract = payload.get("source_contract", {})
    if isinstance(source_contract, dict):
        source_items = [
            ("Source", source_contract.get("source") or payload.get("source") or "nasdaq-turnaround-screener"),
            ("Freshness", source_contract.get("freshness") or payload.get("source_freshness") or "unknown"),
            ("Reliability label", source_contract.get("reliability_label") or payload.get("source_reliability") or "unknown"),
        ]
        if source_contract.get("source_report_path"):
            source_items.append(("Source report path", source_contract.get("source_report_path")))
        lines.extend(f"- **{label}**: {value}" for label, value in source_items)
        if source_contract.get("market_data_reliability"):
            lines.append(f"- **Market data reliability**: {source_contract['market_data_reliability']}")

    lines.append("")
    lines.append("## Data quality")
    raw_data_quality = payload.get("data_quality", {})
    data_quality = dict(raw_data_quality) if isinstance(raw_data_quality, dict) else {}
    provider_statuses = list(data_quality.pop("market_data_provider_status", []))
    for key, value in data_quality.items():
        if key in {"reliability_label", "market_data_reliability"}:
            continue
        lines.append(f"- **{_pretty_key(key)}**: {value}")
    if provider_statuses:
        lines.append("")
        lines.append("### Market data sources")
        lines.extend(f"- {_format_provider_status(status)}" for status in provider_statuses)
        reliability = payload.get("source_contract", {}).get("reliability_label") or payload.get("data_quality", {}).get("reliability_label") or payload.get("data_quality", {}).get("market_data_reliability")
        if reliability:
            lines.append(f"- **Reliability label**: {reliability}")

    previous_feedback_lines = _build_previous_top3_feedback_section_lines(payload)
    if previous_feedback_lines:
        lines.extend([""] + previous_feedback_lines)
    lines.extend([""] + _build_watchlist_section_lines(payload))
    lines.extend([""] + _build_missing_tickers_section_lines(payload))
    lines.extend([""] + _build_discovery_section_lines(payload))
    lines.extend([""] + _build_overlay_section_lines(payload))
    lines.extend([""] + _build_consumer_messaging_section_lines(payload))
    return "\n".join(lines) + "\n"


def write_assistant_briefing(
    payload: dict[str, Any],
    markdown: str,
    output_dir: Path,
    *,
    artifact_basename: str | None = None,
) -> tuple[Path, Path]:
    json_name, markdown_name = _assistant_artifact_names(artifact_basename)
    json_path = write_json(output_dir / json_name, payload)
    markdown_path = write_text(output_dir / markdown_name, markdown)
    return json_path, markdown_path


def _assistant_artifact_names(artifact_basename: str | None) -> tuple[str, str]:
    if artifact_basename is None:
        return JSON_ARTIFACT_NAME, MARKDOWN_ARTIFACT_NAME

    basename = artifact_basename.strip()
    if not basename:
        raise ValueError("artifact basename cannot be blank")
    basename_path = Path(basename)
    if basename_path.name != basename or basename_path.suffix:
        raise ValueError("artifact basename must be a filename stem without path separators or extension")
    return f"{basename}.json", f"{basename}.md"


def _dedupe_tickers(tickers: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in tickers:
        try:
            ticker = normalize_ticker(value)
        except ValueError:
            continue
        if ticker in seen:
            continue
        normalized.append(ticker)
        seen.add(ticker)
    return normalized


def _build_data_quality(daily_report: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "planned_ticker_count",
        "successful_ticker_count",
        "failed_ticker_count",
        "bars_nonempty_count",
        "latest_bar_date_mismatch_count",
        "insufficient_history_count",
        "candidate_count",
    ]
    data_quality = {key: daily_report.get(key, 0) for key in keys}
    provider_statuses = _sanitize_provider_statuses(daily_report.get("market_data_provider_status", []))
    if provider_statuses:
        data_quality["market_data_provider_status"] = provider_statuses
        reliability_label = daily_report.get("reliability_label") or derive_market_data_reliability_label(provider_statuses)
        data_quality["reliability_label"] = reliability_label
        data_quality["market_data_reliability"] = reliability_label
    elif daily_report.get("reliability_label"):
        reliability_label = str(daily_report.get("reliability_label"))
        data_quality["reliability_label"] = reliability_label
        data_quality["market_data_reliability"] = reliability_label
    return data_quality


def _derive_market_data_reliability(provider_statuses: list[dict[str, Any]]) -> str:
    if any(status.get("status") in {"failed", "rate_limited"} for status in provider_statuses):
        return "degraded"
    if any(status.get("status") == "partial_success" for status in provider_statuses):
        return "partial"
    if any(status.get("role") == "fallback" and int(status.get("successful_ticker_count") or 0) > 0 for status in provider_statuses):
        return "fallback_used"
    return "ok"


def _sanitize_provider_statuses(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    allowed_keys = {
        "provider",
        "role",
        "status",
        "attempted_ticker_count",
        "successful_ticker_count",
        "failed_ticker_count",
        "error_kind",
        "rate_limited",
        "retry_count",
        "used_cache",
        "used_stale_cache",
        "cooldown_active",
        "fallback_provider",
        "target_date",
        "cache_checked_ticker_count",
        "cache_found_ticker_count",
        "cache_hit_ticker_count",
        "cache_target_date_coverage_count",
        "cache_target_date_miss_count",
        "cache_target_date_coverage_ratio",
        "cache_latest_bar_date_min",
        "cache_latest_bar_date_max",
        "cache_target_date_miss_sample",
        "downloaded_ticker_count",
    }
    sanitized: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        sanitized.append({key: item.get(key) for key in sorted(allowed_keys) if key in item})
    return sanitized


def _review_stage_label(tier: str | None) -> str:
    return _REVIEW_STAGE_LABELS.get(str(tier or ""), "보류")


def _review_stage_reason(
    *,
    tier: str | None,
    in_screener_universe: bool,
    data_failure: bool,
) -> str:
    if data_failure:
        return "데이터 실패로 추가 검토가 필요합니다"
    if not in_screener_universe:
        return "소스 스크리너 유니버스 밖입니다"
    if tier == "buy-review":
        return "기술 신호는 충족했지만 밸류에이션·품질·촉매는 별도 확인이 필요합니다"
    if tier == "watchlist":
        return "기술 신호는 있으나 아직 검토 전 단계입니다"
    if tier == "avoid/high-risk":
        return "리스크가 높아 우선순위가 낮습니다"
    return "추가 확인이 필요합니다"


def _candidate_explanation_fields(candidate: dict[str, Any]) -> dict[str, Any]:
    tier = str(candidate.get("tier") or "")
    tier_reasons = _normalize_text_items(candidate.get("tier_reasons"))
    risk_flags = _normalize_text_items(candidate.get("risk_flags")) or _normalize_text_items(candidate.get("risks"))
    blocking_items = _dedupe_text_items([*tier_reasons, *risk_flags])

    base_reason = _review_stage_reason(tier=tier, in_screener_universe=True, data_failure=False)
    if tier == "buy-review":
        why_not_buy_review = "이미 buy-review 조건은 충족했습니다; 그래도 밸류에이션·사업 품질·촉매는 별도 확인이 필요합니다."
    elif tier_reasons:
        why_not_buy_review = f"{base_reason}: {'; '.join(tier_reasons)}"
    else:
        why_not_buy_review = base_reason

    if blocking_items:
        improve_note = f"해소 필요: {'; '.join(blocking_items)}"
    elif tier == "buy-review":
        improve_note = "유지 필요: 기술 신호와 리스크 상태를 재확인하고 밸류에이션·품질·촉매를 별도 검증"
    else:
        improve_note = "개선 필요: risk-adjusted 점수, 기술적 확인, 리스크 프로필"

    return {
        "risk_flags": risk_flags,
        "why_not_buy_review_qualified": why_not_buy_review,
        "what_would_need_to_improve": improve_note,
    }


def _normalize_text_items(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return _dedupe_text_items(str(item).strip() for item in value if str(item).strip())


def _dedupe_text_items(items: Any) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = str(item).strip()
        key = " ".join(text.casefold().split())
        if not text or key in seen:
            continue
        normalized.append(text)
        seen.add(key)
    return normalized


def _review_stage_interpretation(
    *,
    tier: str | None,
    in_screener_universe: bool,
    data_failure: bool,
) -> str:
    stage = _review_stage_label(tier)
    return f"{stage}: {_review_stage_reason(tier=tier, in_screener_universe=in_screener_universe, data_failure=data_failure)}"


def _format_assistant_stage(item: dict[str, Any]) -> str:
    return _review_stage_label(item.get("tier") if item.get("is_candidate") else None)


def _format_assistant_stage_reason(item: dict[str, Any]) -> str:
    return _review_stage_reason(
        tier=item.get("tier") if item.get("is_candidate") else None,
        in_screener_universe=bool(item.get("in_screener_universe")),
        data_failure=bool(item.get("data_failure")),
    )


def _format_assistant_interpretation(item: dict[str, Any]) -> str:
    return _review_stage_interpretation(
        tier=item.get("tier") if item.get("is_candidate") else None,
        in_screener_universe=bool(item.get("in_screener_universe")),
        data_failure=bool(item.get("data_failure")),
    )


def _format_candidate_explanation_lines(candidate: dict[str, Any], *, indent: str) -> list[str]:
    lines: list[str] = []
    risk_flags = _normalize_text_items(candidate.get("risk_flags")) or _normalize_text_items(candidate.get("risks"))
    tier_reasons = _normalize_text_items(candidate.get("tier_reasons"))
    if risk_flags:
        lines.append(f"{indent}Risk flags: {'; '.join(risk_flags)}")
    if tier_reasons:
        lines.append(f"{indent}Tier reasons: {'; '.join(tier_reasons)}")
    if candidate.get("why_not_buy_review_qualified"):
        lines.append(f"{indent}Why not buy-review qualified: {candidate['why_not_buy_review_qualified']}")
    if candidate.get("what_would_need_to_improve"):
        lines.append(f"{indent}What would need to improve: {candidate['what_would_need_to_improve']}")
    return lines


def _format_provider_status(status: Any) -> str:
    if not isinstance(status, dict):
        return "unknown source: unknown"
    provider = str(status.get("provider") or "unknown")
    role = str(status.get("role") or "source")
    state = str(status.get("status") or "unknown")
    attempted = status.get("attempted_ticker_count", "n/a")
    successful = status.get("successful_ticker_count", "n/a")
    parts = [f"**{role} {provider}**", f"status={state}", f"tickers={successful}/{attempted}"]
    if status.get("fallback_provider"):
        parts.append(f"fallback={status['fallback_provider']}")
    if status.get("rate_limited"):
        parts.append("rate_limited=true")
    if status.get("used_stale_cache"):
        parts.append("cache=stale")
    elif status.get("used_cache"):
        parts.append("cache=hit")
    if status.get("target_date"):
        parts.append(f"target_date={status['target_date']}")
    if status.get("cache_latest_bar_date_max"):
        parts.append(f"cache_latest={status['cache_latest_bar_date_max']}")
    if status.get("cache_target_date_miss_count") is not None:
        parts.append(f"cache_target_miss={status['cache_target_date_miss_count']}")
    if status.get("error_kind"):
        parts.append(f"error={status['error_kind']}")
    return " | ".join(parts)


def _parse_data_failures(data_failures: Any) -> dict[str, str]:
    failures: dict[str, str] = {}
    for item in data_failures or []:
        text = str(item)
        ticker, separator, reason = text.partition(":")
        if not separator:
            continue
        normalized_ticker = ticker.strip().upper()
        if normalized_ticker and normalized_ticker not in failures:
            failures[normalized_ticker] = reason.strip()
    return failures


def _build_user_ticker_item(
    ticker: str,
    planned_tickers: set[str],
    candidate_by_ticker: dict[str, dict[str, Any]],
    rank_by_ticker: dict[str, int],
    data_failures_by_ticker: dict[str, str],
    daily_report: dict[str, Any],
    tracked_contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    candidate = candidate_by_ticker.get(ticker)
    data_failure_reason = data_failures_by_ticker.get(ticker)
    data_failure = data_failure_reason is not None
    if candidate is None:
        item = {
            "ticker": ticker,
            "in_screener_universe": ticker in planned_tickers,
            "is_candidate": False,
            "rank": None,
            "name": None,
            "score": None,
            "risk_adjusted_score": None,
            "tier": None,
            "tier_reasons": [],
            "reasons": [],
            "risks": [],
            "review_stage": _review_stage_label(None),
            "review_stage_reason": _review_stage_reason(
                tier=None,
                in_screener_universe=ticker in planned_tickers,
                data_failure=data_failure,
            ),
            "data_failure": data_failure,
            "data_failure_reason": data_failure_reason,
            "assistant_interpretation": _format_assistant_interpretation(
                {
                    "tier": None,
                    "is_candidate": False,
                    "in_screener_universe": ticker in planned_tickers,
                    "data_failure": data_failure,
                }
            ),
        }
        return {**item, **_tracked_ticker_fields(item, tracked_contract=tracked_contract)}

    review_stage = _review_stage_label(str(candidate.get("tier") or None))
    item = {
        **_compact_candidate(candidate, rank=rank_by_ticker[ticker], daily_report=daily_report),
        "in_screener_universe": ticker in planned_tickers,
        "is_candidate": True,
        "review_stage": review_stage,
        "review_stage_reason": _review_stage_reason(
            tier=str(candidate.get("tier") or None),
            in_screener_universe=ticker in planned_tickers,
            data_failure=data_failure,
        ),
        "data_failure": data_failure,
        "data_failure_reason": data_failure_reason,
        "assistant_interpretation": _format_assistant_interpretation(
            {
                "tier": candidate.get("tier"),
                "is_candidate": True,
                "in_screener_universe": ticker in planned_tickers,
                "data_failure": data_failure,
            }
        ),
    }
    return {**item, **_tracked_ticker_fields(item, tracked_contract=tracked_contract)}


def _tracked_ticker_fields(item: dict[str, Any], *, tracked_contract: dict[str, Any] | None) -> dict[str, Any]:
    contract = tracked_contract or {}
    briefing_section = str(contract.get("briefing_section") or "watchlist")
    briefing_label_family = str(contract.get("briefing_label_family") or "watchlist")
    tracking_lane = str(contract.get("tracking_lane") or briefing_section)
    briefing_label = _briefing_label_for_item(item, family=briefing_label_family)
    return {
        "tracking_lane": tracking_lane,
        "briefing_section": briefing_section,
        "briefing_label_family": briefing_label_family,
        "briefing_label": briefing_label,
        "briefing_interpretation": _briefing_interpretation_for_item(
            item,
            family=briefing_label_family,
            label=briefing_label,
        ),
    }


def _briefing_label_for_item(item: dict[str, Any], *, family: str) -> str:
    data_failure = bool(item.get("data_failure"))
    in_screener_universe = bool(item.get("in_screener_universe"))
    tier = str(item.get("tier") or "") if item.get("is_candidate") else ""

    if family == "holding":
        if data_failure:
            return "일부 점검 필요"
        if not in_screener_universe:
            return "정보 부족"
        if tier == "avoid/high-risk":
            return "일부 점검 필요"
        return "모니터"

    if data_failure or not in_screener_universe:
        return "정보 부족"
    if tier == "buy-review":
        return "관심도 상승"
    if tier == "watchlist":
        return "관심도 유지"
    if tier == "avoid/high-risk":
        return "모니터"
    return "정보 부족"


def _briefing_interpretation_for_item(item: dict[str, Any], *, family: str, label: str) -> str:
    data_failure = bool(item.get("data_failure"))
    in_screener_universe = bool(item.get("in_screener_universe"))
    tier = str(item.get("tier") or "") if item.get("is_candidate") else ""

    if family == "holding":
        if data_failure:
            return f"{label}: 스크리너 데이터 실패로 holdings lane에서 추가 점검이 필요합니다"
        if not in_screener_universe:
            return f"{label}: 소스 스크리너 유니버스 밖이라 holdings lane에서는 기술 신호를 확정하지 않습니다"
        if tier == "avoid/high-risk":
            return f"{label}: 기술 리스크 플래그가 있어 holdings lane에서 점검 우선순위를 올립니다"
        return f"{label}: 기술 신호는 보조 참고용이며 holdings thesis 영향은 별도 확인이 필요합니다"

    return f"{label}: {_format_assistant_stage_reason(item)}"


def _compact_candidate(
    candidate: dict[str, Any],
    *,
    rank: int,
    daily_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    compact: dict[str, Any] = {
        "rank": rank,
        "ticker": str(candidate.get("ticker", "")).upper(),
        "name": candidate.get("name"),
        "score": candidate.get("score"),
        "risk_adjusted_score": candidate.get("risk_adjusted_score"),
        "tier": candidate.get("tier"),
        "tier_reasons": list(candidate.get("tier_reasons") or []),
        "reasons": list(candidate.get("reasons") or []),
        "risks": list(candidate.get("risks") or []),
        **_candidate_explanation_fields(candidate),
        "source_provenance": _candidate_source_provenance(candidate, daily_report=daily_report),
    }

    sector = _clean_optional_text(candidate.get("sector"))
    industry = _clean_optional_text(candidate.get("industry"))
    if sector:
        compact["sector"] = sector
    if industry:
        compact["industry"] = industry

    relative_context = _build_relative_strength_context(candidate)
    if relative_context:
        compact["relative_strength_context"] = relative_context
        sector_proxy = _sector_proxy(candidate, sector)
        if sector_proxy:
            compact["sector_proxy"] = sector_proxy
        compact["setup_context"] = _classify_setup_context(relative_context)

    return compact


def _candidate_source_provenance(
    candidate: dict[str, Any],
    *,
    daily_report: dict[str, Any] | None,
) -> dict[str, Any]:
    raw = candidate.get("source_provenance") or candidate.get("provenance")
    if isinstance(raw, dict):
        source_type = _normalize_source_type(raw.get("source_type") or raw.get("type"))
        source_timestamp = _first_present(
            raw,
            "source_timestamp",
            "latest_source_timestamp",
            "latest_source_date",
            "filing_date",
            "published_at",
        )
        if source_timestamp is None and source_type in {"market data", "fallback"}:
            source_timestamp = (daily_report or {}).get("generated_at") or (daily_report or {}).get("date")
        return {
            "source_type": source_type,
            "source_name": raw.get("source_name") or raw.get("name") or raw.get("form") or source_type,
            "source_timestamp": str(source_timestamp) if source_timestamp is not None else None,
            "freshness_label": str(raw.get("freshness_label") or _freshness_label_for_source(source_type)),
        }

    source_type = _normalize_source_type(
        candidate.get("source_type") or candidate.get("evidence_source_type") or candidate.get("filing_source_type")
    )
    source_timestamp = _first_present(
        candidate,
        "source_timestamp",
        "latest_source_timestamp",
        "latest_source_date",
        "filing_date",
        "published_at",
    )
    if source_type != "fallback" or source_timestamp is not None:
        if source_timestamp is None and source_type == "market data":
            source_timestamp = (daily_report or {}).get("generated_at") or (daily_report or {}).get("date")
        return {
            "source_type": source_type,
            "source_name": candidate.get("source_name") or candidate.get("filing_form") or source_type,
            "source_timestamp": str(source_timestamp) if source_timestamp is not None else None,
            "freshness_label": _freshness_label_for_source(source_type),
        }

    return _market_data_source_provenance(daily_report)


def _market_data_source_provenance(daily_report: dict[str, Any] | None) -> dict[str, Any]:
    report = daily_report or {}
    provider_statuses = _sanitize_provider_statuses(report.get("market_data_provider_status", []))
    providers = [str(status.get("provider")) for status in provider_statuses if status.get("provider")]
    used_fallback = any(status.get("role") == "fallback" or status.get("fallback_provider") for status in provider_statuses)
    source_type = "fallback" if used_fallback else "market data"
    freshness = (
        str(report.get("reliability_label") or derive_market_data_reliability_label(provider_statuses))
        if provider_statuses
        else "market data"
    )
    return {
        "source_type": source_type,
        "source_name": ", ".join(providers) if providers else "daily market data",
        "source_timestamp": report.get("generated_at") or report.get("date"),
        "freshness_label": freshness,
    }


def _normalize_source_type(value: Any) -> str:
    text = str(value or "fallback").strip().lower().replace("_", "-")
    if text in {"sec", "sec filing", "filing", "10-k", "10-q", "8-k"}:
        return "SEC filing"
    if text in {"ir", "ir release", "investor relations", "press release", "earnings release"}:
        return "IR release"
    if text in {"market", "market-data", "market data", "price data", "prices"}:
        return "market data"
    if text in {"fallback", "secondary", "fallback data"}:
        return "fallback"
    return str(value).strip() if value else "fallback"


def _freshness_label_for_source(source_type: str) -> str:
    if source_type in {"SEC filing", "IR release"}:
        return "official"
    if source_type == "market data":
        return "market data"
    return "fallback"


def _first_present(mapping: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value not in (None, ""):
            return value
    return None


def _format_source_provenance(provenance: Any) -> str | None:
    if not isinstance(provenance, dict):
        return None
    parts = [f"provenance {provenance.get('source_type') or 'unknown'}"]
    if provenance.get("source_name"):
        parts.append(str(provenance["source_name"]))
    if provenance.get("source_timestamp"):
        parts.append(f"latest={provenance['source_timestamp']}")
    parts.append(f"freshness={provenance.get('freshness_label') or 'unknown'}")
    return " | ".join(parts)


def _build_relative_strength_context(candidate: dict[str, Any]) -> dict[str, float]:
    snapshot = candidate.get("indicator_snapshot")
    if not isinstance(snapshot, dict):
        snapshot = {}
    keys = (
        "stock_return_20d",
        "qqq_return_20d",
        "rel_strength_20d_vs_qqq",
        "sector_return_20d",
        "rel_strength_20d_vs_sector",
    )
    context: dict[str, float] = {}
    for key in keys:
        value = candidate.get(key, snapshot.get(key))
        if isinstance(value, bool) or value is None:
            continue
        try:
            context[key] = round(float(value), 2)
        except (TypeError, ValueError):
            continue
    return context


def _sector_proxy(candidate: dict[str, Any], sector: str | None) -> str | None:
    snapshot = candidate.get("indicator_snapshot")
    if not isinstance(snapshot, dict):
        snapshot = {}
    for key in ("sector_proxy", "sector_proxy_ticker", "sector_etf"):
        value = _clean_optional_text(candidate.get(key) or snapshot.get(key))
        if value:
            return value.upper()
    if not sector:
        return None
    return SECTOR_PROXY_TICKERS.get(sector.lower()) or SECTOR_PROXY_TICKERS.get(sector.lower().replace(" ", "_"))


def _classify_setup_context(relative_context: dict[str, float]) -> str:
    vs_qqq = relative_context.get("rel_strength_20d_vs_qqq")
    vs_sector = relative_context.get("rel_strength_20d_vs_sector")
    sector_return = relative_context.get("sector_return_20d")

    if vs_sector is not None and vs_sector >= 0 and sector_return is not None and sector_return < 0:
        return "idiosyncratic rebound inside weak sector"
    if vs_sector is not None and vs_sector < 0 and sector_return is not None and sector_return < 0:
        return "sector-wide mean reversion laggard"
    if vs_qqq is not None and vs_qqq >= 0:
        return "benchmark-relative rebound"
    if sector_return is not None and sector_return < 0:
        return "sector-wide mean reversion"
    return "mixed relative-strength setup"


def _format_sector_relative_context(candidate: dict[str, Any]) -> str | None:
    parts: list[str] = []
    sector = candidate.get("sector")
    industry = candidate.get("industry")
    if sector and industry:
        parts.append(f"sector {sector} / industry {industry}")
    elif sector:
        parts.append(f"sector {sector}")
    elif industry:
        parts.append(f"industry {industry}")

    relative_context = candidate.get("relative_strength_context")
    if isinstance(relative_context, dict):
        vs_qqq = relative_context.get("rel_strength_20d_vs_qqq")
        if isinstance(vs_qqq, (int, float)) and not isinstance(vs_qqq, bool):
            parts.append(f"20d vs QQQ {_format_pp(float(vs_qqq))}")
        vs_sector = relative_context.get("rel_strength_20d_vs_sector")
        if isinstance(vs_sector, (int, float)) and not isinstance(vs_sector, bool):
            sector_proxy = candidate.get("sector_proxy") or "sector proxy"
            parts.append(f"vs {sector_proxy} {_format_pp(float(vs_sector))}")

    setup_context = candidate.get("setup_context")
    if setup_context:
        parts.append(f"setup: {setup_context}")
    return " | ".join(parts) if parts else None


def _format_pp(value: float) -> str:
    return f"{value:+.1f}pp"


def _clean_optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _missing_reason(ticker: str) -> str:
    return "Not in source screener universe"


def _pretty_key(key: str) -> str:
    return key.replace("_", " ").capitalize()

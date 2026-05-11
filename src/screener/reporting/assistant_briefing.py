from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from screener.storage.files import write_json, write_text
from screener.universe import normalize_ticker

JSON_ARTIFACT_NAME = "latest-user-briefing-screener.json"
MARKDOWN_ARTIFACT_NAME = "latest-user-briefing-screener.md"

_NO_SIGNAL_INTERPRETATION = "No technical turnaround candidate signal from the screener today."
_CANDIDATE_INTERPRETATION = "Technical turnaround candidate signal from the screener today."


def parse_user_tickers(raw: str) -> list[str]:
    return _dedupe_tickers([part.strip() for part in raw.replace("\n", ",").split(",")])


def load_daily_report(report_path: Path) -> dict[str, Any]:
    return json.loads(report_path.read_text(encoding="utf-8"))


def build_assistant_briefing_payload(
    daily_report: dict[str, Any],
    *,
    user_tickers: list[str],
    top_candidate_count: int = 5,
    generated_at: datetime,
    source_report_path: Path | None = None,
) -> dict[str, Any]:
    data_quality = _build_data_quality(daily_report)
    candidate_rows = list(daily_report.get("candidates", []))
    candidate_by_ticker = {str(row.get("ticker", "")).upper(): row for row in candidate_rows}
    rank_by_ticker = {str(row.get("ticker", "")).upper(): index + 1 for index, row in enumerate(candidate_rows)}
    planned_tickers = {str(ticker).upper() for ticker in daily_report.get("planned_tickers", [])}
    data_failures_by_ticker = _parse_data_failures(daily_report.get("data_failures", []))

    payload: dict[str, Any] = {
        "schema_version": 1,
        "source": "nasdaq-turnaround-screener",
        "generated_at": generated_at.isoformat(),
        "screener_date": daily_report.get("date"),
        "source_report_path": str(source_report_path) if source_report_path is not None else None,
        "universe": daily_report.get("universe"),
        "data_quality": data_quality,
        "user_tickers": [],
        "missing_user_tickers": [],
        "top_candidates": [],
        "notes": [
            "Signals are technical/research signals only and not buy/sell advice.",
        ],
    }

    for ticker in _dedupe_tickers(user_tickers):
        item = _build_user_ticker_item(
            ticker,
            planned_tickers,
            candidate_by_ticker,
            rank_by_ticker,
            data_failures_by_ticker,
        )
        payload["user_tickers"].append(item)
        if not item.get("in_screener_universe"):
            payload["missing_user_tickers"].append({"ticker": ticker, "reason": _missing_reason(ticker)})

    for row in candidate_rows[: max(0, top_candidate_count)]:
        candidate = _compact_candidate(row, rank=rank_by_ticker.get(str(row.get("ticker", "")).upper(), 0))
        payload["top_candidates"].append(candidate)

    return payload


def build_assistant_briefing_markdown(payload: dict[str, Any]) -> str:
    lines = [
        f"# NASDAQ Screener Assistant Briefing ({payload.get('screener_date')})",
        "",
        "These signals are decision-support only and not buy/sell advice.",
        "",
        "## Data quality",
    ]
    raw_data_quality = payload.get("data_quality", {})
    data_quality = dict(raw_data_quality) if isinstance(raw_data_quality, dict) else {}
    provider_statuses = list(data_quality.pop("market_data_provider_status", []))
    for key, value in data_quality.items():
        lines.append(f"- **{_pretty_key(key)}**: {value}")
    if provider_statuses:
        lines.append("")
        lines.append("### Market data sources")
        lines.extend(f"- {_format_provider_status(status)}" for status in provider_statuses)

    lines.extend(["", "## User holdings/watchlist technical signal summary"])
    for item in payload.get("user_tickers", []):
        if item.get("is_candidate"):
            lines.append(
                f"- **{item['ticker']}**: candidate rank {item.get('rank')} | score {item.get('score')} | "
                f"risk-adjusted {item.get('risk_adjusted_score')} | tier {item.get('tier')}"
            )
        else:
            summary = f"- **{item['ticker']}**: not a candidate"
            if item.get("data_failure"):
                summary += f" | data failure: {item.get('data_failure_reason')}"
            if not item.get("in_screener_universe"):
                summary += " | outside screener universe"
            lines.append(summary)

    lines.extend(["", "## Missing tickers / outside universe"])
    missing_items = payload.get("missing_user_tickers", [])
    if missing_items:
        lines.extend(f"- **{item['ticker']}**: {item['reason']}" for item in missing_items)
    else:
        lines.append("- None")

    universe_name = payload.get("universe") or "source screener universe"
    lines.extend(["", f"## Top {universe_name} turnaround candidates"])
    top_candidates = payload.get("top_candidates", [])
    if top_candidates:
        for candidate in top_candidates:
            heading = candidate["ticker"]
            if candidate.get("name"):
                heading += f" ({candidate['name']})"
            lines.append(
                f"- **#{candidate['rank']} {heading}**: score {candidate.get('score')} | "
                f"risk-adjusted {candidate.get('risk_adjusted_score')} | tier {candidate.get('tier')}"
            )
    else:
        lines.append("- None")

    lines.extend(["", "## Notes"])
    lines.extend(f"- {note}" for note in payload.get("notes", []))
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
    return data_quality


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
    }
    sanitized: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        sanitized.append({key: item.get(key) for key in sorted(allowed_keys) if key in item})
    return sanitized


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
) -> dict[str, Any]:
    candidate = candidate_by_ticker.get(ticker)
    data_failure_reason = data_failures_by_ticker.get(ticker)
    data_failure = data_failure_reason is not None
    if candidate is None:
        return {
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
            "data_failure": data_failure,
            "data_failure_reason": data_failure_reason,
            "assistant_interpretation": _NO_SIGNAL_INTERPRETATION,
        }

    return {
        **_compact_candidate(candidate, rank=rank_by_ticker[ticker]),
        "in_screener_universe": ticker in planned_tickers,
        "is_candidate": True,
        "data_failure": data_failure,
        "data_failure_reason": data_failure_reason,
        "assistant_interpretation": _CANDIDATE_INTERPRETATION,
    }


def _compact_candidate(candidate: dict[str, Any], *, rank: int) -> dict[str, Any]:
    return {
        "rank": rank,
        "ticker": str(candidate.get("ticker", "")).upper(),
        "name": candidate.get("name"),
        "score": candidate.get("score"),
        "risk_adjusted_score": candidate.get("risk_adjusted_score"),
        "tier": candidate.get("tier"),
        "tier_reasons": list(candidate.get("tier_reasons") or []),
        "reasons": list(candidate.get("reasons") or []),
        "risks": list(candidate.get("risks") or []),
    }


def _missing_reason(ticker: str) -> str:
    return "Not in source screener universe"


def _pretty_key(key: str) -> str:
    return key.replace("_", " ").capitalize()

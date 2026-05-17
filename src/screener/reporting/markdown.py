from __future__ import annotations

from screener.models import CandidateResult, PreviousCandidateOutcome, ScreenRunResult


def build_markdown_report(result: ScreenRunResult) -> str:
    metadata = result.metadata
    lines = [
        f"# NASDAQ Turnaround Screener Report ({metadata.run_date.isoformat()})",
        "",
        f"- **Universe**: {metadata.universe}",
        f"- **Run mode**: {metadata.run_mode}",
        f"- **Dry run**: {metadata.dry_run}",
        f"- **Candidate count**: {result.candidate_count}",
        "",
    ]

    if result.previous_candidate_outcomes:
        lines.append("## Previous Candidate T+1 Outcomes")
        for outcome in result.previous_candidate_outcomes:
            lines.append(_format_previous_candidate_outcome(outcome))
        lines.append("")

    if metadata.notes:
        lines.append("## Notes")
        lines.extend(f"- {note}" for note in metadata.notes)
        lines.append("")

    if metadata.data_failures:
        lines.append("## Data Failures")
        lines.extend(f"- {failure}" for failure in metadata.data_failures)
        lines.append("")

    if metadata.market_data_provider_status:
        lines.append("## Market Data Provider Status")
        lines.extend(_provider_status_line(status) for status in metadata.market_data_provider_status)
        if metadata.reliability_label:
            lines.append(f"- **Reliability label**: {metadata.reliability_label}")
        lines.append("")

    if not result.candidates:
        lines.append("## Buy Review Candidates")
        lines.append("- No buy-review candidates.")
        lines.append("")
        lines.append("## Candidates")
        lines.append("- No candidates matched the current screening rules.")
        return "\n".join(lines) + "\n"

    buy_review_candidates = [candidate for candidate in result.candidates if candidate.tier == "buy-review"]
    lines.append("## Buy Review Candidates")
    if not buy_review_candidates:
        lines.append("- No buy-review candidates.")
        lines.append("")
    else:
        for candidate in buy_review_candidates:
            lines.extend(_format_candidate_block(candidate, include_tier=False))

    lines.append("## Candidates")
    for candidate in result.candidates:
        lines.extend(_format_candidate_block(candidate, include_tier=True))

    return "\n".join(lines)


def _provider_status_line(status: dict[str, object]) -> str:
    provider = str(status.get("provider") or "unknown")
    role = str(status.get("role") or "source")
    state = str(status.get("status") or "unknown")
    attempted = status.get("attempted_ticker_count", "n/a")
    successful = status.get("successful_ticker_count", "n/a")
    failed = status.get("failed_ticker_count", "n/a")
    parts = [f"- **{role} {provider}**: {state}", f"tickers {successful}/{attempted} ok", f"failed {failed}"]
    if status.get("fallback_provider"):
        parts.append(f"fallback {status['fallback_provider']}")
    if status.get("rate_limited"):
        parts.append("rate_limited")
    if status.get("retry_count"):
        parts.append(f"retries {status['retry_count']}")
    if status.get("used_stale_cache"):
        parts.append("stale_cache")
    elif status.get("used_cache"):
        parts.append("cache")
    if status.get("cooldown_active"):
        parts.append("cooldown")
    if status.get("error_kind"):
        parts.append(f"error {status['error_kind']}")
    return " | ".join(parts)


def _format_previous_candidate_outcome(outcome: PreviousCandidateOutcome) -> str:
    heading = outcome.ticker if not outcome.name else f"{outcome.ticker} ({outcome.name})"
    percent = "n/a" if outcome.percent_return is None else f"{outcome.percent_return:+.2f}%"
    absolute = "n/a" if outcome.absolute_return is None else f"{outcome.absolute_return:+.2f}"
    current_close = "n/a" if outcome.current_close is None else f"{outcome.current_close:.2f}"
    previous_close = "n/a" if outcome.previous_close is None else f"{outcome.previous_close:.2f}"
    return (
        f"- **{heading}**: T+1 {percent} ({absolute}) | "
        f"close {previous_close} → {current_close} | "
        f"prior tier {outcome.previous_tier or 'n/a'}, score {outcome.previous_score or 'n/a'}"
    )


def _format_candidate_block(candidate: CandidateResult, *, include_tier: bool) -> list[str]:
    heading = candidate.ticker if not candidate.name else f"{candidate.ticker} ({candidate.name})"
    lines = [f"### {heading}"]
    lines.append(f"- **Score**: {candidate.score}")
    lines.append(_risk_adjusted_score_line(candidate.risk_adjusted_score))
    if include_tier:
        lines.append(f"- **Tier**: {candidate.tier}")
    if candidate.tier_reasons:
        lines.append("- **Tier reasons**:")
        lines.extend(f"  - {reason}" for reason in candidate.tier_reasons)
    if candidate.reasons:
        lines.append("- **Reasons**:")
        lines.extend(f"  - {reason}" for reason in candidate.reasons)
    else:
        lines.append("- **Reasons**: n/a")
    if candidate.risks:
        lines.append("- **Risks**:")
        lines.extend(f"  - {risk}" for risk in candidate.risks)
    else:
        lines.append("- **Risks**: n/a")
    lines.append("")
    return lines


def _risk_adjusted_score_line(risk_adjusted_score: int | None) -> str:
    if risk_adjusted_score is None:
        return "- **Risk-adjusted score**: n/a"
    return f"- **Risk-adjusted score**: {risk_adjusted_score}"

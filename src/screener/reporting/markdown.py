from __future__ import annotations

from screener.models import ScreenRunResult


def build_markdown_report(result: ScreenRunResult) -> str:
    metadata = result.metadata
    lines = [
        f"# NASDAQ Turnaround Screener Report ({metadata.run_date.isoformat()})",
        "",
        f"- universe: {metadata.universe}",
        f"- run_mode: {metadata.run_mode}",
        f"- dry_run: {metadata.dry_run}",
        f"- candidate_count: {result.candidate_count}",
        "",
    ]

    if metadata.notes:
        lines.append("## Notes")
        lines.extend(f"- {note}" for note in metadata.notes)
        lines.append("")

    if metadata.data_failures:
        lines.append("## Data Failures")
        lines.extend(f"- {failure}" for failure in metadata.data_failures)
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
            heading = candidate.ticker if not candidate.name else f"{candidate.ticker} ({candidate.name})"
            lines.extend(
                [
                    f"### {heading}",
                    f"- score: {candidate.score}",
                    f"- tier_reasons: {', '.join(candidate.tier_reasons) if candidate.tier_reasons else 'n/a'}",
                    f"- reasons: {', '.join(candidate.reasons) if candidate.reasons else 'n/a'}",
                    f"- risks: {', '.join(candidate.risks) if candidate.risks else 'n/a'}",
                    "",
                ]
            )

    lines.append("## Candidates")
    for candidate in result.candidates:
        heading = candidate.ticker if not candidate.name else f"{candidate.ticker} ({candidate.name})"
        lines.extend(
            [
                f"### {heading}",
                f"- score: {candidate.score}",
                f"- tier: {candidate.tier}",
                f"- reasons: {', '.join(candidate.reasons) if candidate.reasons else 'n/a'}",
                f"- risks: {', '.join(candidate.risks) if candidate.risks else 'n/a'}",
                "",
            ]
        )

    return "\n".join(lines)

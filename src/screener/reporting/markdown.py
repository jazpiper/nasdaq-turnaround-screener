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

    lines.append("## Candidates")
    if not result.candidates:
        lines.append("- No candidates matched the current screening rules.")
        return "\n".join(lines) + "\n"

    for candidate in result.candidates:
        heading = candidate.ticker if not candidate.name else f"{candidate.ticker} ({candidate.name})"
        lines.extend(
            [
                f"### {heading}",
                f"- score: {candidate.score}",
                f"- reasons: {', '.join(candidate.reasons) if candidate.reasons else 'n/a'}",
                f"- risks: {', '.join(candidate.risks) if candidate.risks else 'n/a'}",
                "",
            ]
        )

    return "\n".join(lines)

from __future__ import annotations

from screener.models import ScreenRunResult


def build_json_report(result: ScreenRunResult) -> dict:
    return {
        "date": result.metadata.run_date.isoformat(),
        "generated_at": result.metadata.generated_at.isoformat(),
        "universe": result.metadata.universe,
        "run_mode": result.metadata.run_mode,
        "dry_run": result.metadata.dry_run,
        "candidate_count": result.candidate_count,
        "candidates": [candidate.model_dump(mode="json") for candidate in result.candidates],
    }

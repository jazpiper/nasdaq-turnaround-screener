from __future__ import annotations

from screener.models import ScreenRunResult


def build_json_report(result: ScreenRunResult) -> dict:
    return {
        "date": result.metadata.run_date.isoformat(),
        "generated_at": result.metadata.generated_at.isoformat(),
        "universe": result.metadata.universe,
        "run_mode": result.metadata.run_mode,
        "dry_run": result.metadata.dry_run,
        "planned_ticker_count": result.metadata.planned_ticker_count,
        "successful_ticker_count": result.metadata.successful_ticker_count,
        "failed_ticker_count": result.metadata.failed_ticker_count,
        "bars_nonempty_count": result.metadata.bars_nonempty_count,
        "latest_bar_date_mismatch_count": result.metadata.latest_bar_date_mismatch_count,
        "insufficient_history_count": result.metadata.insufficient_history_count,
        "planned_tickers": list(result.metadata.planned_tickers),
        "candidate_count": result.candidate_count,
        "data_failures": list(result.metadata.data_failures),
        "notes": list(result.metadata.notes),
        "candidates": [candidate.model_dump(mode="json") for candidate in result.candidates],
    }

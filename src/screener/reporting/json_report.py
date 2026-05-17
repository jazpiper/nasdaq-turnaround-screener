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
        "market_data_provider_status": [dict(status) for status in result.metadata.market_data_provider_status],
        "reliability_label": result.metadata.reliability_label,
        "run_started_at": result.metadata.run_started_at.isoformat() if result.metadata.run_started_at else None,
        "run_completed_at": result.metadata.run_completed_at.isoformat() if result.metadata.run_completed_at else None,
        "run_duration_seconds": result.metadata.run_duration_seconds,
        "run_status": result.metadata.run_status,
        "quality_gate": result.metadata.quality_gate,
        "quality_gate_reasons": list(result.metadata.quality_gate_reasons),
        "observability": dict(result.metadata.observability),
        "notes": list(result.metadata.notes),
        "previous_candidate_outcomes": [outcome.model_dump(mode="json") for outcome in result.previous_candidate_outcomes],
        "candidates": [candidate.model_dump(mode="json") for candidate in result.candidates],
    }

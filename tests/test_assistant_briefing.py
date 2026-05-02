from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from screener.reporting.assistant_briefing import (
    JSON_ARTIFACT_NAME,
    MARKDOWN_ARTIFACT_NAME,
    build_assistant_briefing_markdown,
    build_assistant_briefing_payload,
    parse_user_tickers,
    write_assistant_briefing,
)


def sample_daily_report() -> dict:
    return {
        "date": "2026-05-01",
        "generated_at": "2026-05-01T16:30:46-04:00",
        "universe": "NASDAQ-100",
        "run_mode": "daily",
        "dry_run": False,
        "planned_ticker_count": 100,
        "successful_ticker_count": 100,
        "failed_ticker_count": 0,
        "bars_nonempty_count": 100,
        "latest_bar_date_mismatch_count": 0,
        "insufficient_history_count": 0,
        "planned_tickers": ["TSLA", "PLTR", "GOOGL", "NVDA", "GEHC"],
        "candidate_count": 2,
        "data_failures": [],
        "notes": [],
        "candidates": [
            {
                "ticker": "GEHC",
                "name": "GE HealthCare Technologies Inc.",
                "score": 68,
                "risk_adjusted_score": 53,
                "tier": "avoid/high-risk",
                "tier_reasons": ["too many unresolved risk flags"],
                "reasons": ["BB 하단 근처 또는 재진입 구간"],
                "risks": ["주봉 추세가 아직 약함"],
            },
            {
                "ticker": "PLTR",
                "name": "Palantir Technologies Inc.",
                "score": 72,
                "risk_adjusted_score": 69,
                "tier": "watchlist",
                "tier_reasons": [],
                "reasons": ["최근 2일 이상 종가 개선"],
                "risks": ["시장/섹터 맥락 확인이 필요함"],
            },
        ],
    }


def test_parse_user_tickers_normalizes_deduplicates_and_preserves_order() -> None:
    tickers = parse_user_tickers("tsla, INFQ,pltr, tsla, googl, nvda")

    assert tickers == ["TSLA", "INFQ", "PLTR", "GOOGL", "NVDA"]


def test_parse_user_tickers_matches_universe_ticker_normalization() -> None:
    tickers = parse_user_tickers(" brk.b, brk-b, , tsla ")

    assert tickers == ["BRK-B", "TSLA"]


def test_briefing_payload_summarizes_user_tickers_missing_entries_and_top_candidates() -> None:
    payload = build_assistant_briefing_payload(
        sample_daily_report(),
        user_tickers=["TSLA", "INFQ", "PLTR", "RKLB", "GOOGL", "NVDA"],
        top_candidate_count=1,
        generated_at=datetime(2026, 5, 2, 12, 0, tzinfo=timezone.utc),
        source_report_path=Path("output/daily/latest/daily-report.json"),
    )

    assert payload["schema_version"] == 1
    assert payload["source"] == "nasdaq-turnaround-screener"
    assert payload["generated_at"] == "2026-05-02T12:00:00+00:00"
    assert payload["screener_date"] == "2026-05-01"
    assert payload["data_quality"] == {
        "planned_ticker_count": 100,
        "successful_ticker_count": 100,
        "failed_ticker_count": 0,
        "bars_nonempty_count": 100,
        "latest_bar_date_mismatch_count": 0,
        "insufficient_history_count": 0,
        "candidate_count": 2,
    }

    user_by_ticker = {item["ticker"]: item for item in payload["user_tickers"]}
    assert user_by_ticker["TSLA"]["in_screener_universe"] is True
    assert user_by_ticker["TSLA"]["is_candidate"] is False
    assert user_by_ticker["TSLA"]["score"] is None
    assert user_by_ticker["TSLA"]["assistant_interpretation"] == "No technical turnaround candidate signal from the screener today."

    assert user_by_ticker["PLTR"]["in_screener_universe"] is True
    assert user_by_ticker["PLTR"]["is_candidate"] is True
    assert user_by_ticker["PLTR"]["rank"] == 2
    assert user_by_ticker["PLTR"]["score"] == 72
    assert user_by_ticker["PLTR"]["risk_adjusted_score"] == 69
    assert user_by_ticker["PLTR"]["tier"] == "watchlist"

    assert user_by_ticker["INFQ"]["in_screener_universe"] is False
    assert user_by_ticker["RKLB"]["in_screener_universe"] is False
    missing_reasons = {item["ticker"]: item["reason"] for item in payload["missing_user_tickers"]}
    assert missing_reasons["RKLB"] == "Not in source screener universe"
    assert missing_reasons["INFQ"] == "Not in source screener universe"

    assert payload["top_candidates"] == [
        {
            "rank": 1,
            "ticker": "GEHC",
            "name": "GE HealthCare Technologies Inc.",
            "score": 68,
            "risk_adjusted_score": 53,
            "tier": "avoid/high-risk",
            "tier_reasons": ["too many unresolved risk flags"],
            "reasons": ["BB 하단 근처 또는 재진입 구간"],
            "risks": ["주봉 추세가 아직 약함"],
        }
    ]
    assert "technical/research signals only" in payload["notes"][0]


def test_markdown_briefing_includes_required_sections_and_caution() -> None:
    payload = build_assistant_briefing_payload(
        sample_daily_report(),
        user_tickers=["TSLA", "INFQ", "PLTR", "RKLB", "GOOGL", "NVDA"],
        top_candidate_count=1,
        generated_at=datetime(2026, 5, 2, 12, 0, tzinfo=timezone.utc),
    )

    markdown = build_assistant_briefing_markdown(payload)

    assert "# NASDAQ Screener Assistant Briefing (2026-05-01)" in markdown
    assert "## Data quality" in markdown
    assert "planned_ticker_count: 100" in markdown
    assert "## User holdings/watchlist technical signal summary" in markdown
    assert "TSLA: not a candidate" in markdown
    assert "PLTR: candidate rank 2" in markdown
    assert "## Missing tickers / outside universe" in markdown
    assert "INFQ: Not in source screener universe" in markdown
    assert "## Top NASDAQ-100 turnaround candidates" in markdown
    assert "GEHC (GE HealthCare Technologies Inc.)" in markdown
    assert "not buy/sell advice" in markdown


def test_write_assistant_briefing_uses_stable_artifact_names(tmp_path: Path) -> None:
    payload = build_assistant_briefing_payload(
        sample_daily_report(),
        user_tickers=["TSLA"],
        top_candidate_count=1,
        generated_at=datetime(2026, 5, 2, 12, 0, tzinfo=timezone.utc),
    )
    markdown = build_assistant_briefing_markdown(payload)

    json_path, markdown_path = write_assistant_briefing(payload, markdown, tmp_path)

    assert json_path == tmp_path / JSON_ARTIFACT_NAME
    assert markdown_path == tmp_path / MARKDOWN_ARTIFACT_NAME
    assert json.loads(json_path.read_text(encoding="utf-8"))["screener_date"] == "2026-05-01"
    assert markdown_path.read_text(encoding="utf-8") == markdown


def test_user_watchlist_payload_marks_failed_planned_ticker_without_missing_it() -> None:
    report = {
        **sample_daily_report(),
        "universe": "user-watchlist",
        "planned_ticker_count": 6,
        "successful_ticker_count": 5,
        "failed_ticker_count": 1,
        "bars_nonempty_count": 5,
        "planned_tickers": ["TSLA", "INFQ", "PLTR", "RKLB", "GOOGL", "NVDA"],
        "data_failures": ["INFQ: No price rows returned"],
        "candidate_count": 1,
        "candidates": [
            {
                "ticker": "RKLB",
                "name": None,
                "score": 66,
                "risk_adjusted_score": 60,
                "tier": "watchlist",
                "tier_reasons": [],
                "reasons": ["최근 2일 이상 종가 개선"],
                "risks": [],
            }
        ],
    }

    payload = build_assistant_briefing_payload(
        report,
        user_tickers=["TSLA", "INFQ", "PLTR", "RKLB", "GOOGL", "NVDA"],
        top_candidate_count=3,
        generated_at=datetime(2026, 5, 2, 12, 0, tzinfo=timezone.utc),
    )

    user_by_ticker = {item["ticker"]: item for item in payload["user_tickers"]}
    assert payload["universe"] == "user-watchlist"
    assert payload["missing_user_tickers"] == []
    assert user_by_ticker["INFQ"]["in_screener_universe"] is True
    assert user_by_ticker["INFQ"]["is_candidate"] is False
    assert user_by_ticker["INFQ"]["data_failure"] is True
    assert user_by_ticker["INFQ"]["data_failure_reason"] == "No price rows returned"
    assert user_by_ticker["RKLB"]["is_candidate"] is True


def test_write_assistant_briefing_accepts_custom_artifact_basename(tmp_path: Path) -> None:
    payload = build_assistant_briefing_payload(
        sample_daily_report(),
        user_tickers=["TSLA"],
        top_candidate_count=0,
        generated_at=datetime(2026, 5, 2, 12, 0, tzinfo=timezone.utc),
    )
    markdown = build_assistant_briefing_markdown(payload)

    json_path, markdown_path = write_assistant_briefing(
        payload,
        markdown,
        tmp_path,
        artifact_basename="latest-user-watchlist-screener",
    )

    assert json_path == tmp_path / "latest-user-watchlist-screener.json"
    assert markdown_path == tmp_path / "latest-user-watchlist-screener.md"

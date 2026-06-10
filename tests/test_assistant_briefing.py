from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from screener.reporting.assistant_briefing import (
    JSON_ARTIFACT_NAME,
    MARKDOWN_ARTIFACT_NAME,
    _build_consumer_messaging_section_lines,
    _build_discovery_section_lines,
    _build_watchlist_section_lines,
    build_assistant_briefing_markdown,
    build_assistant_briefing_payload,
    load_user_universe_contract,
    parse_user_tickers,
    write_assistant_briefing,
)


def sample_user_universe_contract() -> dict[str, dict[str, object]]:
    return {
        "TSLA": {"tracking_lane": "holdings", "briefing_section": "holdings", "briefing_label_family": "holding"},
        "INFQ": {"tracking_lane": "holdings", "briefing_section": "holdings", "briefing_label_family": "holding"},
        "PLTR": {"tracking_lane": "holdings", "briefing_section": "holdings", "briefing_label_family": "holding"},
        "RKLB": {"tracking_lane": "focus_watchlist", "briefing_section": "watchlist", "briefing_label_family": "watchlist"},
        "GOOGL": {"tracking_lane": "focus_watchlist", "briefing_section": "watchlist", "briefing_label_family": "watchlist"},
        "NVDA": {"tracking_lane": "big_tech_p1", "briefing_section": "watchlist", "briefing_label_family": "watchlist"},
    }


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
        tracked_ticker_contract=sample_user_universe_contract(),
    )

    assert payload["schema_version"] == 2
    assert payload["source"] == "nasdaq-turnaround-screener"
    assert payload["source_freshness"] == "fresh"
    assert payload["generated_at"] == "2026-05-02T12:00:00+00:00"

    assert payload["source_contract"] == {
        "source": "nasdaq-turnaround-screener",
        "source_report_path": "output/daily/latest/daily-report.json",
        "freshness": "fresh",
        "reliability_label": "unofficial",
        "market_data_reliability": "unofficial",
    }
    assert payload["data_quality"] == {
        "planned_ticker_count": 100,
        "successful_ticker_count": 100,
        "failed_ticker_count": 0,
        "bars_nonempty_count": 100,
        "latest_bar_date_mismatch_count": 0,
        "insufficient_history_count": 0,
        "candidate_count": 2,
    }
    assert payload["overlay_candidates"] == [
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
            "risk_flags": ["주봉 추세가 아직 약함"],
            "why_not_buy_review_qualified": "리스크가 높아 우선순위가 낮습니다: too many unresolved risk flags",
            "what_would_need_to_improve": "해소 필요: too many unresolved risk flags; 주봉 추세가 아직 약함",
            "source_provenance": {
                "source_type": "market data",
                "source_name": "daily market data",
                "source_timestamp": "2026-05-01T16:30:46-04:00",
                "freshness_label": "market data",
            },
        }
    ]

    user_by_ticker = {item["ticker"]: item for item in payload["user_tickers"]}
    assert user_by_ticker["TSLA"]["in_screener_universe"] is True
    assert user_by_ticker["TSLA"]["is_candidate"] is False
    assert user_by_ticker["TSLA"]["review_stage"] == "보류"
    assert user_by_ticker["TSLA"]["briefing_section"] == "holdings"
    assert user_by_ticker["TSLA"]["briefing_label_family"] == "holding"
    assert user_by_ticker["TSLA"]["briefing_label"] == "모니터"
    assert user_by_ticker["TSLA"]["assistant_interpretation"] == "보류: 추가 확인이 필요합니다"

    assert user_by_ticker["PLTR"]["in_screener_universe"] is True
    assert user_by_ticker["PLTR"]["is_candidate"] is True
    assert user_by_ticker["PLTR"]["rank"] == 2
    assert user_by_ticker["PLTR"]["score"] == 72
    assert user_by_ticker["PLTR"]["risk_adjusted_score"] == 69
    assert user_by_ticker["PLTR"]["tier"] == "watchlist"
    assert user_by_ticker["PLTR"]["review_stage"] == "관심"
    assert user_by_ticker["PLTR"]["briefing_section"] == "holdings"
    assert user_by_ticker["PLTR"]["briefing_label_family"] == "holding"
    assert user_by_ticker["PLTR"]["briefing_label"] == "모니터"
    assert user_by_ticker["PLTR"]["briefing_interpretation"] == "모니터: 기술 신호는 보조 참고용이며 holdings thesis 영향은 별도 확인이 필요합니다"
    assert user_by_ticker["PLTR"]["assistant_interpretation"] == "관심: 기술 신호는 있으나 아직 검토 전 단계입니다"
    assert user_by_ticker["PLTR"]["risk_flags"] == ["시장/섹터 맥락 확인이 필요함"]
    assert user_by_ticker["PLTR"]["why_not_buy_review_qualified"] == "기술 신호는 있으나 아직 검토 전 단계입니다"
    assert user_by_ticker["PLTR"]["what_would_need_to_improve"] == "해소 필요: 시장/섹터 맥락 확인이 필요함"
    assert user_by_ticker["PLTR"]["source_provenance"] == {
        "source_type": "market data",
        "source_name": "daily market data",
        "source_timestamp": "2026-05-01T16:30:46-04:00",
        "freshness_label": "market data",
    }

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
            "risk_flags": ["주봉 추세가 아직 약함"],
            "why_not_buy_review_qualified": "리스크가 높아 우선순위가 낮습니다: too many unresolved risk flags",
            "what_would_need_to_improve": "해소 필요: too many unresolved risk flags; 주봉 추세가 아직 약함",
            "source_provenance": {
                "source_type": "market data",
                "source_name": "daily market data",
                "source_timestamp": "2026-05-01T16:30:46-04:00",
                "freshness_label": "market data",
            },
        }
    ]
    assert "technical/research signals only" in payload["notes"][0]


def test_briefing_payload_includes_candidate_source_provenance_and_freshness() -> None:
    report = sample_daily_report()
    report["candidates"][0]["source_provenance"] = {
        "source_type": "SEC filing",
        "source_name": "10-Q",
        "source_timestamp": "2026-04-30",
        "freshness_label": "official recent",
    }
    report["candidates"][1]["source_provenance"] = {
        "source_type": "IR release",
        "source_name": "Q1 earnings release",
        "source_timestamp": "2026-05-01T13:00:00-04:00",
        "freshness_label": "official same-day",
    }

    payload = build_assistant_briefing_payload(
        report,
        user_tickers=["PLTR"],
        top_candidate_count=2,
        generated_at=datetime(2026, 5, 2, 12, 0, tzinfo=timezone.utc),
        tracked_ticker_contract=sample_user_universe_contract(),
    )
    markdown = build_assistant_briefing_markdown(payload)

    top_by_ticker = {item["ticker"]: item for item in payload["top_candidates"]}
    assert top_by_ticker["GEHC"]["source_provenance"] == {
        "source_type": "SEC filing",
        "source_name": "10-Q",
        "source_timestamp": "2026-04-30",
        "freshness_label": "official recent",
    }
    assert "PLTR" not in top_by_ticker

    user_by_ticker = {item["ticker"]: item for item in payload["user_tickers"]}
    assert user_by_ticker["PLTR"]["source_provenance"]["source_name"] == "Q1 earnings release"
    assert "provenance SEC filing" in markdown
    assert "freshness=official recent" in markdown
    assert "provenance IR release" in markdown
    assert "latest=2026-05-01T13:00:00-04:00" in markdown


def test_briefing_sections_are_split_by_audience() -> None:
    payload = build_assistant_briefing_payload(
        sample_daily_report(),
        user_tickers=["TSLA", "PLTR"],
        top_candidate_count=1,
        generated_at=datetime(2026, 5, 2, 12, 0, tzinfo=timezone.utc),
        tracked_ticker_contract=sample_user_universe_contract(),
        previous_top3_feedback={
            "available": True,
            "source_run_date": "2026-04-30",
            "horizon_label": "D+1",
            "filled_count": 1,
            "no_fill_count": 0,
            "negative_return_count": 1,
            "items": [
                {
                    "rank": 1,
                    "ticker": "AAPL",
                    "name": "Apple Inc.",
                    "fill_status": "filled",
                    "absolute_return_pct": -1.25,
                    "relative_return_vs_spy_pct": -0.8,
                    "exit_reason": "horizon_close",
                    "warning_flags": ["손실", "SPY 미만"],
                }
            ],
        },
    )

    watchlist_lines = _build_watchlist_section_lines(payload)
    discovery_lines = _build_discovery_section_lines(payload)
    notes_lines = _build_consumer_messaging_section_lines(payload)
    markdown = build_assistant_briefing_markdown(payload)

    assert watchlist_lines[0] == "## User universe tracking"
    assert "### Holdings lane" in watchlist_lines
    assert "### Watchlist / basket lane" in watchlist_lines
    assert discovery_lines[0] == "## New discovery candidates"
    assert notes_lines[0] == "## Notes"
    assert any(line.startswith("- **PLTR**: 모니터 | holding lane") for line in watchlist_lines)
    assert any(line.startswith("- **#1 GEHC") for line in discovery_lines)
    assert "## Previous Top3 outcome feedback" in markdown
    assert "- **#1 AAPL (Apple Inc.)**: 체결 | return -1.25% | vs SPY -0.80% | exit horizon_close | warning 손실, SPY 미만" in markdown
    assert markdown.index("## Previous Top3 outcome feedback") < markdown.index("## User universe tracking")
    assert markdown.index("## User universe tracking") < markdown.index("## New discovery candidates")
    assert markdown.index("## New discovery candidates") < markdown.index("## Notes")


def test_briefing_payload_uses_report_timestamp_for_market_data_source_without_candidate_timestamp() -> None:
    report = sample_daily_report()
    report["candidates"][0]["source_type"] = "market data"
    report["candidates"][0]["source_name"] = "twelve-data"

    payload = build_assistant_briefing_payload(
        report,
        user_tickers=[],
        top_candidate_count=1,
        generated_at=datetime(2026, 5, 2, 12, 0, tzinfo=timezone.utc),
    )

    assert payload["top_candidates"][0]["source_provenance"] == {
        "source_type": "market data",
        "source_name": "twelve-data",
        "source_timestamp": "2026-05-01T16:30:46-04:00",
        "freshness_label": "market data",
    }


def test_briefing_payload_adds_sector_relative_context_and_setup_classification() -> None:
    report = sample_daily_report()
    report["candidates"] = [
        {
            **report["candidates"][0],
            "sector": "health_care",
            "industry": "Medical Devices",
            "indicator_snapshot": {
                "stock_return_20d": -6.2,
                "qqq_return_20d": -3.0,
                "rel_strength_20d_vs_qqq": -3.2,
                "sector_proxy_ticker": "XLV",
                "sector_return_20d": -7.1,
                "rel_strength_20d_vs_sector": 0.9,
            },
        }
    ]

    payload = build_assistant_briefing_payload(
        report,
        user_tickers=["GEHC"],
        top_candidate_count=1,
        generated_at=datetime(2026, 5, 2, 12, 0, tzinfo=timezone.utc),
    )
    markdown = build_assistant_briefing_markdown(payload)
    candidate = payload["user_tickers"][0]

    assert candidate["sector"] == "health_care"
    assert candidate["industry"] == "Medical Devices"
    assert candidate["sector_proxy"] == "XLV"
    assert candidate["relative_strength_context"] == {
        "stock_return_20d": -6.2,
        "qqq_return_20d": -3.0,
        "rel_strength_20d_vs_qqq": -3.2,
        "sector_return_20d": -7.1,
        "rel_strength_20d_vs_sector": 0.9,
    }
    assert candidate["setup_context"] == "idiosyncratic rebound inside weak sector"
    assert "sector health_care / industry Medical Devices" in markdown
    assert "20d vs QQQ -3.2pp" in markdown
    assert "vs XLV +0.9pp" in markdown
    assert "setup: idiosyncratic rebound inside weak sector" in markdown


def test_briefing_payload_exposes_provider_status_without_raw_sensitive_message() -> None:
    report = {
        **sample_daily_report(),
        "market_data_provider_status": [
            {
                "provider": "twelve-data",
                "role": "primary",
                "status": "partial_success",
                "attempted_ticker_count": 100,
                "successful_ticker_count": 95,
                "failed_ticker_count": 5,
                "error_kind": "rate_limited",
                "rate_limited": True,
                "retry_count": 2,
                "used_stale_cache": True,
                "fallback_provider": "yfinance",
                "message": "raw token=secret-value should not be copied",
            }
        ],
        "reliability_label": "stale",
    }

    payload = build_assistant_briefing_payload(
        report,
        user_tickers=["TSLA"],
        top_candidate_count=0,
        generated_at=datetime(2026, 5, 2, 12, 0, tzinfo=timezone.utc),
    )
    markdown = build_assistant_briefing_markdown(payload)

    statuses = payload["data_quality"]["market_data_provider_status"]
    assert statuses == [
        {
            "attempted_ticker_count": 100,
            "error_kind": "rate_limited",
            "failed_ticker_count": 5,
            "fallback_provider": "yfinance",
            "provider": "twelve-data",
            "rate_limited": True,
            "retry_count": 2,
            "role": "primary",
            "status": "partial_success",
            "successful_ticker_count": 95,
            "used_stale_cache": True,
        }
    ]
    assert payload["source_contract"]["freshness"] == "stale"
    assert payload["source_contract"]["reliability_label"] == "stale"
    assert payload["source_freshness"] == "stale"
    assert payload["source_reliability"] == "stale"
    assert payload["data_quality"]["reliability_label"] == "stale"
    assert payload["data_quality"]["market_data_reliability"] == "stale"
    assert "## Source / freshness / reliability" in markdown
    assert "**Source**: nasdaq-turnaround-screener" in markdown
    assert "**Freshness**: stale" in markdown
    assert "**Reliability label**: stale" in markdown
    assert "**primary twelve-data**" in markdown
    assert "fallback=yfinance" in markdown
    assert "error=rate_limited" in markdown
    assert "secret-value" not in json.dumps(payload)
    assert "raw token" not in markdown


def test_markdown_briefing_includes_required_sections_and_caution() -> None:
    payload = build_assistant_briefing_payload(
        sample_daily_report(),
        user_tickers=["TSLA", "INFQ", "PLTR", "RKLB", "GOOGL", "NVDA"],
        top_candidate_count=1,
        generated_at=datetime(2026, 5, 2, 12, 0, tzinfo=timezone.utc),
        tracked_ticker_contract=sample_user_universe_contract(),
    )

    markdown = build_assistant_briefing_markdown(payload)

    assert "# NASDAQ Screener Assistant Briefing (2026-05-01)" in markdown
    assert "## Source / freshness / reliability" in markdown
    assert "## Data quality" in markdown
    assert "**Planned ticker count**: 100" in markdown
    assert "## User universe tracking" in markdown
    assert "### Holdings lane" in markdown
    assert "### Watchlist / basket lane" in markdown
    assert "- **TSLA**: 모니터 | holding lane" in markdown
    assert "- **PLTR**: 모니터 | holding lane | technical candidate rank 2" in markdown
    assert "## Missing tickers / outside universe" in markdown
    assert "INFQ: Not in source screener universe" in markdown
    assert "## New discovery candidates" in markdown
    assert "Top NASDAQ-100 review candidates from the screener output." in markdown
    assert "GEHC (GE HealthCare Technologies Inc.)" in markdown
    assert "provenance market data | daily market data" in markdown
    assert "Risk flags: 주봉 추세가 아직 약함" in markdown
    assert "Why not buy-review qualified: 리스크가 높아 우선순위가 낮습니다: too many unresolved risk flags" in markdown
    assert "What would need to improve: 해소 필요: too many unresolved risk flags; 주봉 추세가 아직 약함" in markdown
    assert "## Overlay candidates (outside user universe)" in markdown
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
    written_payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert written_payload["screener_date"] == "2026-05-01"
    assert written_payload["source_contract"]["freshness"] == "fresh"
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


def test_load_user_universe_contract_prioritizes_holdings_lane(tmp_path: Path) -> None:
    path = tmp_path / "us-stocks-universe.json"
    path.write_text(
        json.dumps(
            {
                "coverage_policy": {"priority_order": ["holdings", "focus_watchlist", "big_tech_p1"]},
                "holdings": [{"ticker": "PLTR"}, {"ticker": "TSLA"}],
                "focus_watchlist": ["PLTR", "RKLB"],
                "big_tech_p1": ["NVDA"],
            }
        ),
        encoding="utf-8",
    )

    contract = load_user_universe_contract(path)

    assert contract["PLTR"]["tracking_lane"] == "holdings"
    assert contract["PLTR"]["briefing_section"] == "holdings"
    assert contract["PLTR"]["briefing_label_family"] == "holding"
    assert contract["RKLB"]["tracking_lane"] == "focus_watchlist"
    assert contract["NVDA"]["tracking_lane"] == "big_tech_p1"

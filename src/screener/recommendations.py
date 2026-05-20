from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

ALGORITHM_VERSION = "daily-top3-v0"
SCORE_SCHEMA_VERSION = 1
SNAPSHOT_SCHEMA_VERSION = 2
DEFAULT_BENCHMARK_PRIMARY = "SPY"
DEFAULT_BENCHMARK_SECONDARY = "QQQ"
OUTCOME_HORIZONS = (1, 5, 20, 60)
DEFAULT_EXPECTED_HOLDING_DAYS = 20
PRICE_FORMULA = (
    "reference=latest close; buy_limit=reference*1.01; stop/invalidation=reference*0.92; "
    "targets=reference*1.12/1.24; R/R=(target1-reference)/(reference-stop)"
)


def _round_price(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value, 2)


def _time_stop_date(run_date: Any, expected_holding_days: int) -> str | None:
    if run_date is None:
        return None
    try:
        parsed = datetime.fromisoformat(str(run_date)).date()
    except ValueError:
        return None
    return (parsed + timedelta(days=expected_holding_days)).isoformat()


def build_price_plan(reference_price: Any, *, run_date: Any = None) -> dict[str, Any]:
    """Derive immutable advisory buy/sell levels from the recommendation-time reference price."""
    price = _as_float(reference_price)
    if price is None or price <= 0:
        return {
            "reference_price": price,
            "buy_limit_price": None,
            "stop_loss_price": None,
            "target_sell_price_1": None,
            "target_sell_price_2": None,
            "invalidation_price": None,
            "risk_reward_ratio": None,
            "expected_holding_days": DEFAULT_EXPECTED_HOLDING_DAYS,
            "time_stop_date": _time_stop_date(run_date, DEFAULT_EXPECTED_HOLDING_DAYS),
            "price_method": "close_based_v1",
            "price_formula": PRICE_FORMULA,
        }
    stop = _round_price(price * 0.92)
    target1 = _round_price(price * 1.12)
    risk_reward_ratio = None
    if stop is not None and target1 is not None and price > stop:
        risk_reward_ratio = round((target1 - price) / (price - stop), 2)
    return {
        "reference_price": _round_price(price),
        "buy_limit_price": _round_price(price * 1.01),
        "stop_loss_price": stop,
        "target_sell_price_1": target1,
        "target_sell_price_2": _round_price(price * 1.24),
        "invalidation_price": stop,
        "risk_reward_ratio": risk_reward_ratio,
        "expected_holding_days": DEFAULT_EXPECTED_HOLDING_DAYS,
        "time_stop_date": _time_stop_date(run_date, DEFAULT_EXPECTED_HOLDING_DAYS),
        "price_method": "close_based_v1",
        "price_formula": PRICE_FORMULA,
    }


@dataclass(frozen=True)
class DailyTop3Result:
    run_id: int
    selected_count: int
    json_path: Path
    markdown_path: Path
    payload: dict[str, Any]


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def initialize_recommendation_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            create table if not exists algorithm_versions (
                algorithm_version text primary key,
                score_schema_version integer not null,
                snapshot_schema_version integer not null,
                description text not null,
                created_at text not null,
                active integer not null default 1
            );

            create table if not exists recommendation_runs (
                run_id integer primary key autoincrement,
                algorithm_version text not null references algorithm_versions(algorithm_version),
                run_timestamp text not null,
                run_date text not null,
                universe_name text not null,
                benchmark_primary text not null,
                benchmark_secondary text not null,
                planned_ticker_count integer not null,
                successful_ticker_count integer not null,
                eligible_candidate_count integer not null,
                selected_candidate_count integer not null,
                data_quality_label text not null,
                reliability_label text not null,
                report_path text,
                metadata_path text,
                universe_details_json text not null,
                coverage_json text not null,
                data_failure_summary_json text not null,
                notes_json text not null,
                created_at text not null
            );

            create table if not exists recommendations (
                recommendation_id integer primary key autoincrement,
                run_id integer not null references recommendation_runs(run_id),
                rank integer not null,
                ticker text not null,
                company_name text,
                sector text,
                industry text,
                price real,
                reference_price real,
                buy_limit_price real,
                stop_loss_price real,
                target_sell_price_1 real,
                target_sell_price_2 real,
                invalidation_price real,
                risk_reward_ratio real,
                expected_holding_days integer,
                time_stop_date text,
                price_method text,
                price_formula text,
                close_timestamp text,
                currency text not null default 'USD',
                algorithm_version text not null,
                final_score real not null,
                risk_adjusted_score real not null,
                score_schema_version integer not null,
                snapshot_schema_version integer not null,
                subscore_oversold real not null,
                subscore_bottom_context real not null,
                subscore_reversal real not null,
                subscore_volume real not null,
                subscore_market_context real not null,
                earnings_penalty real not null,
                volatility_penalty real not null,
                severe_weekly_penalty real not null,
                risk_adjustment_penalty real not null,
                rationale_json text not null,
                risk_flags_json text not null,
                tier_reasons_json text not null,
                source_freshness_json text not null,
                data_quality_json text not null,
                benchmark_context_json text not null,
                snapshot_json text not null,
                generated_at text not null
            );

            create table if not exists recommendation_features (
                feature_id integer primary key autoincrement,
                recommendation_id integer not null references recommendations(recommendation_id),
                feature_name text not null,
                feature_value_json text not null,
                created_at text not null
            );

            create table if not exists recommendation_outcomes (
                outcome_id integer primary key autoincrement,
                recommendation_id integer not null references recommendations(recommendation_id),
                horizon_days integer not null,
                horizon_label text not null,
                entry_date text not null,
                horizon_date text,
                entry_price real,
                stop_loss_price real,
                target_sell_price_1 real,
                target_sell_price_2 real,
                invalidation_price real,
                price_method text,
                exit_price real,
                absolute_return real,
                absolute_return_pct real,
                spy_return_pct real,
                qqq_return_pct real,
                relative_return_vs_spy_pct real,
                relative_return_vs_qqq_pct real,
                max_drawdown_pct real,
                max_drawdown_available integer not null default 0,
                drawdown_method text,
                outcome_status text not null default 'pending',
                settled_at text
            );
            """
        )
        _ensure_recommendation_columns(conn)
        conn.execute(
            """
            insert or ignore into algorithm_versions (
                algorithm_version, score_schema_version, snapshot_schema_version,
                description, created_at, active
            ) values (?, ?, ?, ?, ?, 1)
            """,
            (
                ALGORITHM_VERSION,
                SCORE_SCHEMA_VERSION,
                SNAPSHOT_SCHEMA_VERSION,
                "Daily Top 3 buy-review recommendation MVP; advisory only, no broker integration.",
                _iso_now(),
            ),
        )


def _ensure_recommendation_columns(conn: sqlite3.Connection) -> None:
    tables = {row[0] for row in conn.execute("select name from sqlite_master where type = 'table'")}
    if "recommendations" in tables:
        existing = {row[1] for row in conn.execute("pragma table_info(recommendations)")}
        for name, ddl in {
            "reference_price": "real",
            "buy_limit_price": "real",
            "stop_loss_price": "real",
            "target_sell_price_1": "real",
            "target_sell_price_2": "real",
            "invalidation_price": "real",
            "risk_reward_ratio": "real",
            "expected_holding_days": "integer",
            "time_stop_date": "text",
            "price_method": "text",
            "price_formula": "text",
        }.items():
            if name not in existing:
                conn.execute(f"alter table recommendations add column {name} {ddl}")
    if "recommendation_outcomes" in tables:
        existing = {row[1] for row in conn.execute("pragma table_info(recommendation_outcomes)")}
        for name, ddl in {
            "stop_loss_price": "real",
            "target_sell_price_1": "real",
            "target_sell_price_2": "real",
            "invalidation_price": "real",
            "price_method": "text",
        }.items():
            if name not in existing:
                conn.execute(f"alter table recommendation_outcomes add column {name} {ddl}")


def _candidate_snapshot(candidate: dict[str, Any]) -> dict[str, Any]:
    snapshot = candidate.get("indicator_snapshot")
    return dict(snapshot) if isinstance(snapshot, dict) else {}


def _hard_gate_reason(candidate: dict[str, Any]) -> str | None:
    snapshot = _candidate_snapshot(candidate)
    if snapshot.get("weekly_trend_severe_damage") is True:
        return "weekly_trend_severe_damage"
    days_to_earnings = snapshot.get("days_to_next_earnings")
    days_to_earnings_float = _as_float(days_to_earnings)
    if days_to_earnings_float is not None and days_to_earnings_float <= 3.0:
        return "earnings_imminent"
    if _as_float(candidate.get("risk_adjusted_score")) is None:
        return "missing_risk_adjusted_score"
    return None


def select_top3_candidates(daily_report: dict[str, Any], limit: int = 3) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    eligible: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for raw in daily_report.get("candidates", []):
        if not isinstance(raw, dict):
            continue
        candidate = dict(raw)
        reason = _hard_gate_reason(candidate)
        if reason is not None:
            candidate["recommendation_exclusion_reason"] = reason
            excluded.append(candidate)
            continue
        eligible.append(candidate)
    eligible.sort(
        key=lambda item: (
            -float(item.get("risk_adjusted_score") or 0),
            -float(item.get("score") or 0),
            str(item.get("ticker") or ""),
        )
    )
    return eligible[:limit], excluded


def _recommendation_payload_item(
    candidate: dict[str, Any],
    rank: int,
    run_id: int | None = None,
    run_date: Any = None,
) -> dict[str, Any]:
    snapshot = _candidate_snapshot(candidate)
    raw_subscores = candidate.get("subscores")
    subscores: dict[str, Any] = dict(raw_subscores) if isinstance(raw_subscores, dict) else {}
    freshness = {
        "source_provider": snapshot.get("source_provider"),
        "source_timestamp": snapshot.get("source_timestamp") or candidate.get("generated_at"),
        "freshness_label": snapshot.get("freshness_label", "unknown"),
    }
    data_quality = {
        "provider_status": snapshot.get("reliability_label") or "unknown",
        "missing_fields": [key for key in ("close", "low", "bb_lower", "rsi_14", "distance_to_20d_low", "volume_ratio_20d") if snapshot.get(key) is None],
        "bars_available": snapshot.get("bars_available"),
        "insufficient_history": bool(snapshot.get("insufficient_history", False)),
        "notes": [],
    }
    benchmark_context = {
        "benchmark_primary": DEFAULT_BENCHMARK_PRIMARY,
        "benchmark_secondary": DEFAULT_BENCHMARK_SECONDARY,
        "rel_strength_20d_vs_qqq": snapshot.get("rel_strength_20d_vs_qqq"),
        "rel_strength_60d_vs_qqq": snapshot.get("rel_strength_60d_vs_qqq"),
        "market_context_score": snapshot.get("market_context_score"),
    }
    price = candidate.get("close") or snapshot.get("close")
    price_plan = build_price_plan(price, run_date=run_date)
    return {
        "run_id": run_id,
        "rank": rank,
        "ticker": str(candidate.get("ticker", "")),
        "company_name": candidate.get("name"),
        "sector": snapshot.get("sector") or candidate.get("sector"),
        "industry": snapshot.get("industry") or candidate.get("industry"),
        "price": price,
        **price_plan,
        "close_timestamp": snapshot.get("source_timestamp") or candidate.get("generated_at"),
        "currency": snapshot.get("currency", "USD"),
        "algorithm_version": ALGORITHM_VERSION,
        "final_score": candidate.get("score", 0),
        "risk_adjusted_score": candidate.get("risk_adjusted_score") or candidate.get("score", 0),
        "score_schema_version": SCORE_SCHEMA_VERSION,
        "snapshot_schema_version": candidate.get("snapshot_schema_version") or snapshot.get("snapshot_schema_version") or SNAPSHOT_SCHEMA_VERSION,
        "subscores": {
            "oversold": subscores.get("oversold", 0),
            "bottom_context": subscores.get("bottom_context", 0),
            "reversal": subscores.get("reversal", 0),
            "volume": subscores.get("volume", 0),
            "market_context": subscores.get("market_context", 0),
        },
        "penalties": {
            "earnings_penalty": snapshot.get("earnings_penalty", 0),
            "volatility_penalty": snapshot.get("volatility_penalty", 0),
            "severe_weekly_penalty": snapshot.get("severe_weekly_penalty", 0),
            "risk_adjustment_penalty": snapshot.get("risk_adjustment_penalty", 0),
        },
        "rationale": list(candidate.get("reasons") or [])[:2],
        "risk_flags": list(candidate.get("risks") or [])[:4],
        "tier_reasons": list(candidate.get("tier_reasons") or []),
        "source_freshness": freshness,
        "data_quality": data_quality,
        "benchmark_context": benchmark_context,
        "snapshot": snapshot,
        "generated_at": candidate.get("generated_at") or _iso_now(),
    }


def build_daily_top3_payload(daily_report: dict[str, Any], *, run_id: int | None = None) -> dict[str, Any]:
    selected, excluded = select_top3_candidates(daily_report)
    run_date = daily_report.get("date")
    recommendations = [
        _recommendation_payload_item(candidate, rank=index + 1, run_id=run_id, run_date=run_date)
        for index, candidate in enumerate(selected)
    ]
    notes: list[str] = []
    if len(recommendations) < 3:
        notes.append(f"eligible 후보가 {len(recommendations)}개라 Top 3보다 적게 생성됨")
    if excluded:
        notes.append(f"hard gate로 제외된 후보 {len(excluded)}개")
    return {
        "schema_version": 1,
        "source": "nasdaq-turnaround-screener",
        "algorithm_version": ALGORITHM_VERSION,
        "run_id": run_id,
        "run_date": run_date,
        "generated_at": _iso_now(),
        "universe_name": daily_report.get("universe", "NASDAQ-100"),
        "benchmark_primary": DEFAULT_BENCHMARK_PRIMARY,
        "benchmark_secondary": DEFAULT_BENCHMARK_SECONDARY,
        "selection_method": {
            "pipeline": ["universe_filter", "risk_exclusion_gate", "score_components", "diversification_tie_break", "top3_rank"],
            "universe_filter": "Use the daily report universe after data collection coverage/freshness checks.",
            "risk_exclusion_gate": "Exclude imminent earnings <=3 calendar days, severe weekly trend damage, and missing risk_adjusted_score.",
            "score_components": [
                "relative momentum/trend via market_context and QQQ relative strength",
                "technical setup via oversold, bottom_context, and reversal subscores",
                "volume confirmation via volume subscore and volume_ratio_20d snapshot",
                "quality/fundamental proxy via reliability, earnings distance, and data-quality labels",
                "valuation sanity proxy via bottom-distance/Bollinger context in snapshot",
                "catalyst/news proxy via earnings timing and rationale fields",
                "liquidity/volatility risk via volume, ATR/range, and risk penalties",
            ],
            "ranking": "Sort by risk_adjusted_score desc, final_score desc, ticker asc.",
            "diversification_tie_break": "Ticker ascending is the deterministic tie-break for equal scores; no sector cap is applied in MVP.",
            "top3": "Take the first three eligible candidates after gates and ordering.",
        },
        "planned_ticker_count": int(daily_report.get("planned_ticker_count") or 0),
        "successful_ticker_count": int(daily_report.get("successful_ticker_count") or 0),
        "eligible_candidate_count": len(selected) + max(0, len(daily_report.get("candidates", [])) - len(excluded) - len(selected)),
        "selected_candidate_count": len(recommendations),
        "data_quality_label": "degraded" if daily_report.get("data_failures") else "ok",
        "reliability_label": daily_report.get("reliability_label") or daily_report.get("market_data_reliability") or "unknown",
        "recommendations": recommendations,
        "excluded_candidates": [
            {"ticker": item.get("ticker"), "reason": item.get("recommendation_exclusion_reason")}
            for item in excluded
        ],
        "outcomes_status": "pending",
        "last_settlement_date": None,
        "notes": notes,
        "source_daily_report": daily_report,
    }


def build_daily_top3_markdown(payload: dict[str, Any], *, persisted: bool) -> str:
    lines = [
        f"# Daily Top 3 매수추천 ({payload.get('run_date')})",
        "",
        "주의: 이 산출물은 의사결정 보조용 후보 추천이며 자동매수/브로커 연동을 수행하지 않습니다.",
        "",
        "## Top 3",
    ]
    recommendations = payload.get("recommendations", [])
    if not recommendations:
        lines.append("- eligible 후보가 없습니다.")
    for item in recommendations:
        reasons = item.get("rationale") or ["근거 없음"]
        risks = item.get("risk_flags") or ["명시 risk flag 없음"]
        data_quality = item.get("data_quality") or {}
        freshness = item.get("source_freshness") or {}
        lines.extend(
            [
                f"**{item['rank']}) {item['ticker']}** {item.get('company_name') or ''}".rstrip(),
                f"- **기준가**: {item.get('reference_price')}",
                f"- **매수가(상한)**: {item.get('buy_limit_price')}",
                f"- **목표 매도가 1**: {item.get('target_sell_price_1')} / **목표 매도가 2**: {item.get('target_sell_price_2')}",
                f"- **손절/무효화가**: {item.get('stop_loss_price')} / {item.get('invalidation_price')}",
                f"- **R/R·기간·산식**: {item.get('risk_reward_ratio')} / {item.get('expected_holding_days')}일 / {item.get('price_method')}",
                f"- **점수**: {item.get('final_score')} / risk-adjusted {item.get('risk_adjusted_score')}",
                f"- **왜 뽑혔나**: {'; '.join(str(reason) for reason in reasons[:2])}",
                f"- **주의**: {'; '.join(str(risk) for risk in risks[:2])}",
                f"- **데이터**: provider={freshness.get('source_provider') or data_quality.get('provider_status')} / freshness={freshness.get('freshness_label')}",
                f"- **DB**: persisted={'yes' if persisted else 'no'}, run_id={payload.get('run_id')}, outcomes=pending",
                "",
            ]
        )
    lines.extend(
        [
            "## 추천 종목 선정 방식",
            "- universe filter → risk/exclusion gate → score components → diversification/tie-break → Top3 순서로 선정합니다.",
            "- score components: relative momentum/trend, technical setup, volume confirmation, quality/fundamental proxy, valuation sanity, catalyst/news, liquidity/volatility risk.",
            f"- risk_adjusted_score → final_score → ticker 순으로 정렬한 상위 {payload.get('selected_candidate_count')}개입니다.",
            f"- universe={payload.get('universe_name')}, benchmark={payload.get('benchmark_primary')}/{payload.get('benchmark_secondary')}.",
            "",
            "## 사면 안 되는 이유/주의점",
            "- 임박 실적, 심한 주봉 훼손, 낮은 데이터 신뢰도는 hard gate 또는 risk flag로 처리됩니다.",
            "- 변동성/상대약세/거래량 약세는 risk-adjusted score에 반영됩니다.",
            "",
            "## DB 반영 상태",
            f"- persisted: {'yes' if persisted else 'no'}",
            f"- run_id: {payload.get('run_id')}",
            f"- selected_count: {payload.get('selected_candidate_count')}",
            "- outcomes_status: pending",
            f"- last_settlement_date: {payload.get('last_settlement_date')}",
            f"- notes: {'; '.join(payload.get('notes') or ['none'])}",
        ]
    )
    return "\n".join(lines) + "\n"


def _insert_run(conn: sqlite3.Connection, payload: dict[str, Any], markdown_path: Path, json_path: Path) -> int:
    cursor = conn.execute(
        """
        insert into recommendation_runs (
            algorithm_version, run_timestamp, run_date, universe_name, benchmark_primary, benchmark_secondary,
            planned_ticker_count, successful_ticker_count, eligible_candidate_count, selected_candidate_count,
            data_quality_label, reliability_label, report_path, metadata_path, universe_details_json,
            coverage_json, data_failure_summary_json, notes_json, created_at
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            payload["algorithm_version"],
            payload["generated_at"],
            payload["run_date"],
            payload["universe_name"],
            payload["benchmark_primary"],
            payload["benchmark_secondary"],
            payload["planned_ticker_count"],
            payload["successful_ticker_count"],
            payload["eligible_candidate_count"],
            payload["selected_candidate_count"],
            payload["data_quality_label"],
            payload["reliability_label"],
            str(markdown_path),
            str(json_path),
            _json_dumps({"universe_name": payload["universe_name"]}),
            _json_dumps({"planned": payload["planned_ticker_count"], "successful": payload["successful_ticker_count"]}),
            _json_dumps(payload.get("source_daily_report", {}).get("data_failures", [])),
            _json_dumps(payload.get("notes", [])),
            _iso_now(),
        ),
    )
    return int(cursor.lastrowid or 0)


def _insert_recommendations(conn: sqlite3.Connection, payload: dict[str, Any], run_id: int) -> None:
    for item in payload["recommendations"]:
        item["run_id"] = run_id
        subscores = item["subscores"]
        penalties = item["penalties"]
        cursor = conn.execute(
            """
            insert into recommendations (
                run_id, rank, ticker, company_name, sector, industry, price, reference_price, buy_limit_price,
                stop_loss_price, target_sell_price_1, target_sell_price_2, invalidation_price, risk_reward_ratio,
                expected_holding_days, time_stop_date, price_method, price_formula, close_timestamp, currency,
                algorithm_version, final_score, risk_adjusted_score, score_schema_version, snapshot_schema_version,
                subscore_oversold, subscore_bottom_context, subscore_reversal, subscore_volume, subscore_market_context,
                earnings_penalty, volatility_penalty, severe_weekly_penalty, risk_adjustment_penalty,
                rationale_json, risk_flags_json, tier_reasons_json, source_freshness_json, data_quality_json,
                benchmark_context_json, snapshot_json, generated_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                item["rank"],
                item["ticker"],
                item.get("company_name"),
                item.get("sector"),
                item.get("industry"),
                _as_float(item.get("price")),
                _as_float(item.get("reference_price")),
                _as_float(item.get("buy_limit_price")),
                _as_float(item.get("stop_loss_price")),
                _as_float(item.get("target_sell_price_1")),
                _as_float(item.get("target_sell_price_2")),
                _as_float(item.get("invalidation_price")),
                _as_float(item.get("risk_reward_ratio")),
                int(item["expected_holding_days"]) if item.get("expected_holding_days") is not None else None,
                item.get("time_stop_date"),
                item.get("price_method"),
                item.get("price_formula"),
                item.get("close_timestamp"),
                item.get("currency", "USD"),
                item["algorithm_version"],
                _as_float(item.get("final_score")) or 0,
                _as_float(item.get("risk_adjusted_score")) or 0,
                item["score_schema_version"],
                item["snapshot_schema_version"],
                _as_float(subscores.get("oversold")) or 0,
                _as_float(subscores.get("bottom_context")) or 0,
                _as_float(subscores.get("reversal")) or 0,
                _as_float(subscores.get("volume")) or 0,
                _as_float(subscores.get("market_context")) or 0,
                _as_float(penalties.get("earnings_penalty")) or 0,
                _as_float(penalties.get("volatility_penalty")) or 0,
                _as_float(penalties.get("severe_weekly_penalty")) or 0,
                _as_float(penalties.get("risk_adjustment_penalty")) or 0,
                _json_dumps(item.get("rationale", [])),
                _json_dumps(item.get("risk_flags", [])),
                _json_dumps(item.get("tier_reasons", [])),
                _json_dumps(item.get("source_freshness", {})),
                _json_dumps(item.get("data_quality", {})),
                _json_dumps(item.get("benchmark_context", {})),
                _json_dumps(item.get("snapshot", {})),
                item.get("generated_at") or _iso_now(),
            ),
        )
        recommendation_id = int(cursor.lastrowid or 0)
        for feature_name, feature_value in sorted((item.get("snapshot") or {}).items()):
            conn.execute(
                "insert into recommendation_features (recommendation_id, feature_name, feature_value_json, created_at) values (?, ?, ?, ?)",
                (recommendation_id, feature_name, _json_dumps(feature_value), _iso_now()),
            )
        for horizon in OUTCOME_HORIZONS:
            conn.execute(
                """
                insert into recommendation_outcomes (
                    recommendation_id, horizon_days, horizon_label, entry_date, entry_price, stop_loss_price,
                    target_sell_price_1, target_sell_price_2, invalidation_price, price_method, outcome_status
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')
                """,
                (
                    recommendation_id,
                    horizon,
                    f"D+{horizon}",
                    payload["run_date"],
                    _as_float(item.get("reference_price")),
                    _as_float(item.get("stop_loss_price")),
                    _as_float(item.get("target_sell_price_1")),
                    _as_float(item.get("target_sell_price_2")),
                    _as_float(item.get("invalidation_price")),
                    item.get("price_method"),
                ),
            )


def persist_daily_top3(payload: dict[str, Any], *, db_path: Path, markdown_path: Path, json_path: Path) -> int:
    initialize_recommendation_db(db_path)
    with sqlite3.connect(db_path) as conn:
        run_id = _insert_run(conn, payload, markdown_path, json_path)
        payload["run_id"] = run_id
        _insert_recommendations(conn, payload, run_id)
        return run_id


def write_daily_top3_artifacts(payload: dict[str, Any], output_dir: Path, *, persisted: bool) -> tuple[Path, Path]:
    run_date = str(payload.get("run_date") or "unknown-date")
    artifact_dir = output_dir / run_date
    artifact_dir.mkdir(parents=True, exist_ok=True)
    json_path = artifact_dir / "daily-top3-recommendations.json"
    markdown_path = artifact_dir / "daily-top3-recommendations.md"
    json_path.write_text(_json_dumps(payload) + "\n", encoding="utf-8")
    markdown_path.write_text(build_daily_top3_markdown(payload, persisted=persisted), encoding="utf-8")
    return json_path, markdown_path


def build_daily_top3_recommendations(
    *,
    daily_report_path: Path,
    db_path: Path,
    output_dir: Path,
) -> DailyTop3Result:
    daily_report = json.loads(daily_report_path.read_text(encoding="utf-8"))
    payload = build_daily_top3_payload(daily_report)
    provisional_json_path, provisional_markdown_path = write_daily_top3_artifacts(payload, output_dir, persisted=False)
    run_id = persist_daily_top3(payload, db_path=db_path, markdown_path=provisional_markdown_path, json_path=provisional_json_path)
    payload["run_id"] = run_id
    for item in payload["recommendations"]:
        item["run_id"] = run_id
    json_path, markdown_path = write_daily_top3_artifacts(payload, output_dir, persisted=True)
    return DailyTop3Result(
        run_id=run_id,
        selected_count=int(payload["selected_candidate_count"]),
        json_path=json_path,
        markdown_path=markdown_path,
        payload=payload,
    )

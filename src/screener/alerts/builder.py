from __future__ import annotations

from hashlib import sha1
from typing import Any

from screener.alerts.policy import (
    classify_candidate,
    determine_change_status,
    evaluate_daily_quality_gate,
    evaluate_intraday_quality_gate,
    evaluate_regime_gate,
    headline_reason,
    headline_risk,
    material_signature,
)
from screener.alerts.schema import AlertDocument, AlertEvent, AlertSource, AlertSummary
from screener.alerts.state import AlertState, DigestAlertState, TickerAlertState
from screener.models import CandidateResult, ScreenRunResult
from screener.scoring import WATCHLIST_TIER

SECTOR_CONCENTRATION_CAP = 2
CORRELATION_GROUP_CAP = 2
REPEAT_DIGEST_SCORE_DELTA_CAP = 2
REPEAT_DIGEST_RANK_DELTA_CAP = 1


def _candidate_context_value(candidate, keys: tuple[str, ...]) -> str | None:
    snapshot = candidate.indicator_snapshot or {}
    for key in keys:
        value = snapshot.get(key)
        if value is not None and str(value).strip():
            return str(value)
    return None


def _member_context_value(member: dict[str, object], key: str) -> str | None:
    value = member.get(key)
    if value is not None and str(value).strip():
        return str(value).strip().lower()
    return None


def _build_ticker_alert_state(
    *,
    candidate: CandidateResult,
    rank: int,
    tier: str,
    signature: str,
    generated_at,
    dedupe_key: str,
) -> TickerAlertState:
    snapshot = candidate.indicator_snapshot or {}
    return TickerAlertState(
        last_delivery_tier=tier,
        last_material_signature=signature,
        last_phase="final",
        last_emitted_at=generated_at,
        last_dedupe_key=dedupe_key,
        last_score=candidate.score,
        last_risk_adjusted_score=candidate.risk_adjusted_score,
        last_rank=rank,
        last_headline_reason=headline_reason(candidate),
        last_headline_risk=headline_risk(candidate),
        last_earnings_penalty=int(snapshot.get("earnings_penalty", 0) or 0),
        last_volatility_penalty=int(snapshot.get("volatility_penalty", 0) or 0),
    )


def _should_suppress_repeated_digest_alert(
    previous: TickerAlertState | None,
    *,
    candidate: CandidateResult,
    rank: int,
    signature: str,
) -> bool:
    if previous is None or previous.last_delivery_tier != "digest":
        return False
    if previous.last_material_signature != signature:
        return False

    previous_score = int(previous.last_score if previous.last_score is not None else candidate.score)
    previous_selection_score = int(
        previous.last_risk_adjusted_score
        if previous.last_risk_adjusted_score is not None
        else previous_score
    )
    previous_rank = int(previous.last_rank if previous.last_rank is not None else rank)
    score_delta = abs(candidate.score - previous_score)
    selection_score_delta = abs(
        (candidate.risk_adjusted_score if candidate.risk_adjusted_score is not None else candidate.score)
        - previous_selection_score
    )
    rank_delta = abs(rank - previous_rank)
    return (
        score_delta <= REPEAT_DIGEST_SCORE_DELTA_CAP
        and selection_score_delta <= REPEAT_DIGEST_SCORE_DELTA_CAP
        and rank_delta <= REPEAT_DIGEST_RANK_DELTA_CAP
    )


def _apply_context_cap(
    events: list[AlertEvent],
    digest_members: list[dict[str, object]],
    *,
    key: str,
    cap: int,
) -> tuple[list[AlertEvent], list[dict[str, object]], set[str]]:
    suppressed: set[str] = set()
    counts: dict[str, int] = {}
    items: list[dict[str, object]] = []
    for event in events:
        payload = event.payload
        items.append(
            {
                "ticker": payload.get("ticker"),
                "rank": payload.get("rank"),
                key: payload.get(key),
            }
        )
    items.extend(digest_members)

    for item in sorted(items, key=lambda item: int(item.get("rank") or 10_000)):
        group = _member_context_value(item, key)
        if group is None:
            continue
        counts[group] = counts.get(group, 0) + 1
        if counts[group] > cap and item.get("ticker") is not None:
            suppressed.add(str(item["ticker"]))

    filtered_events = [event for event in events if str(event.payload.get("ticker")) not in suppressed]
    filtered_members = [member for member in digest_members if str(member["ticker"]) not in suppressed]
    return filtered_events, filtered_members, suppressed


def build_daily_alert_document(
    result: ScreenRunResult,
    *,
    state: AlertState,
    artifact_directory: str,
    report_path: str,
    metadata_path: str,
    benchmark_context: dict[str, Any] | None = None,
) -> tuple[AlertDocument, AlertState]:
    quality_gate = evaluate_daily_quality_gate(result.metadata)
    _bc = benchmark_context or {}
    regime = evaluate_regime_gate(
        qqq_below_20d_ma=_bc.get("qqq_below_20d_ma"),
        qqq_return_20d=_bc.get("qqq_return_20d"),
    )
    events: list[AlertEvent] = []
    next_tickers: dict[str, TickerAlertState] = {}
    digest_members: list[dict[str, object]] = []

    for rank, candidate in enumerate(result.candidates, start=1):
        previous = state.tickers.get(candidate.ticker)
        previous_payload = previous.model_dump(mode="json", exclude_none=True) if previous is not None else None
        change_status = determine_change_status(candidate, rank=rank, phase="final", previous_state=previous_payload)
        tier = classify_candidate(candidate, rank=rank, change_status=change_status)
        signature = material_signature(candidate, rank=rank)
        dedupe_key = (
            f"nasdaq-turnaround:{result.metadata.run_date.isoformat()}:{candidate.ticker}:{tier}:"
            f"{sha1(signature.encode('utf-8')).hexdigest()[:8]}"
        )
        ticker_state = _build_ticker_alert_state(
            candidate=candidate,
            rank=rank,
            tier=tier,
            signature=signature,
            generated_at=result.metadata.generated_at,
            dedupe_key=dedupe_key,
        )
        repeated_digest_noise = _should_suppress_repeated_digest_alert(
            previous,
            candidate=candidate,
            rank=rank,
            signature=signature,
        )

        if tier == "single":
            if not repeated_digest_noise:
                events.append(
                    AlertEvent(
                        event_type="ticker_alert",
                        phase="final",
                        delivery_mode="single",
                        delivery_priority="high",
                        severity="warning",
                        dedupe_key=dedupe_key,
                        group_key=f"nasdaq-turnaround:{result.metadata.run_date.isoformat()}:final",
                        change_status=change_status,
                        change_reason_codes=[change_status],
                        message_summary=f"{candidate.ticker} final alert: score {candidate.score}, rank {rank}",
                        payload={
                            "ticker": candidate.ticker,
                            "name": candidate.name,
                            "score": candidate.score,
                            "risk_adjusted_score": candidate.risk_adjusted_score,
                            "tier": candidate.tier,
                            "tier_reasons": list(candidate.tier_reasons),
                            "rank": rank,
                            "subscores": candidate.subscores.model_dump(mode="json"),
                            "reasons": list(candidate.reasons),
                            "risks": list(candidate.risks),
                            "indicator_snapshot": candidate.indicator_snapshot or {},
                            "headline_reason": headline_reason(candidate),
                            "headline_risk": headline_risk(candidate),
                            "market_data_reliability": result.metadata.reliability_label,
                            "sector": _candidate_context_value(candidate, ("sector", "gics_sector")),
                            "correlation_group": _candidate_context_value(
                                candidate,
                                ("correlation_group", "correlation_cluster", "candidate_correlation_group"),
                            ),
                            "source_candidate_ref": f"#/candidates/{rank - 1}",
                        },
                    )
                )
        elif tier == "digest":
            if not repeated_digest_noise:
                digest_members.append(
                    {
                        "ticker": candidate.ticker,
                        "name": candidate.name,
                        "score": candidate.score,
                        "risk_adjusted_score": candidate.risk_adjusted_score,
                        "tier": candidate.tier,
                        "tier_reasons": list(candidate.tier_reasons),
                        "rank": rank,
                        "headline_reason": headline_reason(candidate),
                        "headline_risk": headline_risk(candidate),
                        "market_data_reliability": result.metadata.reliability_label,
                        "sector": _candidate_context_value(candidate, ("sector", "gics_sector")),
                        "correlation_group": _candidate_context_value(
                            candidate,
                            ("correlation_group", "correlation_cluster", "candidate_correlation_group"),
                        ),
                        "change_status": change_status,
                    }
                )

        if tier != "suppressed" or repeated_digest_noise:
            next_tickers[candidate.ticker] = previous if repeated_digest_noise and previous is not None else ticker_state

    sector_capped_tickers: set[str] = set()
    correlation_capped_tickers: set[str] = set()
    sector_concentration_gate = "pass"
    correlation_gate = "pass"
    sector_concentration_cap = SECTOR_CONCENTRATION_CAP if regime.is_bearish else None
    correlation_group_cap = CORRELATION_GROUP_CAP if regime.is_bearish else None
    if regime.is_bearish:
        events, digest_members, sector_capped_tickers = _apply_context_cap(
            events, digest_members, key="sector", cap=SECTOR_CONCENTRATION_CAP
        )
        events, digest_members, correlation_capped_tickers = _apply_context_cap(
            events, digest_members, key="correlation_group", cap=CORRELATION_GROUP_CAP
        )
        sector_concentration_gate = "capped" if sector_capped_tickers else "pass"
        correlation_gate = "capped" if correlation_capped_tickers else "pass"
        for ticker in sector_capped_tickers | correlation_capped_tickers:
            next_tickers.pop(ticker, None)

    capped_watchlist_tickers: set[str] = set()
    if regime.watchlist_cap is not None:
        kept_members: list[dict[str, object]] = []
        watchlist_seen = 0
        for member in digest_members:
            if member["tier"] != WATCHLIST_TIER:
                kept_members.append(member)
                continue
            watchlist_seen += 1
            if watchlist_seen <= regime.watchlist_cap:
                kept_members.append(member)
            else:
                capped_watchlist_tickers.add(str(member["ticker"]))
        digest_members = kept_members
        for ticker in capped_watchlist_tickers:
            next_tickers.pop(ticker, None)

    digest_state: DigestAlertState | None = state.digest
    if digest_members:
        digest_signature = sha1(repr(digest_members).encode("utf-8")).hexdigest()[:8]
        digest_dedupe_key = (
            f"nasdaq-turnaround:{result.metadata.run_date.isoformat()}:final:digest:{digest_signature}"
        )
        events.append(
            AlertEvent(
                event_type="digest_alert",
                phase="final",
                delivery_mode="digest",
                delivery_priority="normal",
                severity="warning" if quality_gate == "warn" else "info",
                dedupe_key=digest_dedupe_key,
                group_key=f"nasdaq-turnaround:{result.metadata.run_date.isoformat()}:final",
                change_status="material_change",
                change_reason_codes=["digest_refresh"],
                message_summary=f"{len(digest_members)} final digest candidates",
                payload={"member_count": len(digest_members), "members": digest_members[:10]},
            )
        )
        digest_state = DigestAlertState(
            last_digest_signature=digest_signature,
            last_digest_dedupe_key=digest_dedupe_key,
        )

    emitted_events = [] if quality_gate == "block" else events

    document = AlertDocument(
        schema_version=1,
        delivery_contract="openclaw-alert-events-v1",
        run_date=result.metadata.run_date.isoformat(),
        generated_at=result.metadata.generated_at.isoformat(),
        run_mode=result.metadata.run_mode,
        phase="final",
        source=AlertSource(
            artifact_directory=artifact_directory,
            report_path=report_path,
            metadata_path=metadata_path,
            window_index=None,
            window_number=None,
            total_windows=None,
        ),
        summary=AlertSummary(
            eligible_candidate_count=len(next_tickers),
            individual_event_count=len([event for event in emitted_events if event.event_type == "ticker_alert"]),
            digest_event_count=len([event for event in emitted_events if event.event_type == "digest_alert"]),
            suppressed_candidate_count=len(result.candidates) - len(next_tickers),
            quality_gate=quality_gate,
            regime_gate=regime.status,
            regime_watchlist_cap=regime.watchlist_cap,
            regime_gate_reason=regime.reason,
            sector_concentration_gate=sector_concentration_gate,
            sector_concentration_cap=sector_concentration_cap,
            suppressed_by_sector_concentration_count=len(sector_capped_tickers),
            correlation_gate=correlation_gate,
            correlation_group_cap=correlation_group_cap,
            suppressed_by_correlation_count=len(correlation_capped_tickers),
            market_data_reliability=result.metadata.reliability_label,
            market_data_provider_status=[dict(status) for status in result.metadata.market_data_provider_status],
        ),
        events=emitted_events,
    )
    if quality_gate == "block":
        return document, AlertState(
            run_date=result.metadata.run_date.isoformat(),
            tickers=dict(state.tickers),
            digest=state.digest,
        )
    return document, AlertState(run_date=result.metadata.run_date.isoformat(), tickers=next_tickers, digest=digest_state)


def build_intraday_alert_document(
    result: ScreenRunResult,
    *,
    collection_result,
    state: AlertState,
    artifact_directory: str,
    report_path: str,
    metadata_path: str,
) -> tuple[AlertDocument, AlertState]:
    collection_quality_gate = evaluate_intraday_quality_gate(
        collected_count=len(collection_result.collected),
        failed_count=len(collection_result.failures),
        skipped_due_to_credit_exhaustion_count=len(collection_result.skipped_due_to_credit_exhaustion),
    )
    document, next_state = build_daily_alert_document(
        result,
        state=state,
        artifact_directory=artifact_directory,
        report_path=report_path,
        metadata_path=metadata_path,
    )
    quality_gate = _merge_quality_gates(document.summary.quality_gate, collection_quality_gate)

    document.phase = "provisional"
    document.run_mode = "intraday-provisional"
    document.source.window_index = collection_result.plan.window_index
    document.source.window_number = collection_result.plan.window_index + 1
    document.source.total_windows = collection_result.plan.total_windows
    document.summary.quality_gate = quality_gate

    if quality_gate == "block":
        document.events = []
        document.summary.individual_event_count = 0
        document.summary.digest_event_count = 0
        return document, AlertState(
            run_date=result.metadata.run_date.isoformat(),
            tickers=dict(state.tickers),
            digest=state.digest,
        )

    adjusted_events: list[AlertEvent] = []
    for event in document.events:
        updates = {
            "phase": "provisional",
            "group_key": event.group_key.removesuffix(":final") + ":provisional",
            "message_summary": event.message_summary.replace(" final ", " provisional "),
        }
        if quality_gate == "warn":
            updates["severity"] = "warning"
        if event.event_type == "digest_alert":
            updates["dedupe_key"] = event.dedupe_key.replace(":final:digest:", ":provisional:digest:")
        adjusted_events.append(event.model_copy(update=updates))
    document.events = adjusted_events
    document.summary.individual_event_count = len([event for event in adjusted_events if event.event_type == "ticker_alert"])
    document.summary.digest_event_count = len([event for event in adjusted_events if event.event_type == "digest_alert"])

    adjusted_tickers = {
        ticker: ticker_state.model_copy(update={"last_phase": "provisional"})
        for ticker, ticker_state in next_state.tickers.items()
    }
    adjusted_digest = next_state.digest
    if adjusted_digest is not None and adjusted_digest.last_digest_dedupe_key is not None:
        adjusted_digest = adjusted_digest.model_copy(
            update={
                "last_digest_dedupe_key": adjusted_digest.last_digest_dedupe_key.replace(
                    ":final:digest:",
                    ":provisional:digest:",
                )
            }
        )

    return document, AlertState(
        run_date=result.metadata.run_date.isoformat(),
        tickers=adjusted_tickers,
        digest=adjusted_digest,
    )


def _merge_quality_gates(*gates: str) -> str:
    if "block" in gates:
        return "block"
    if "warn" in gates:
        return "warn"
    return "pass"

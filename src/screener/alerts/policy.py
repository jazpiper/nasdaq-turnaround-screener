from __future__ import annotations

from dataclasses import dataclass

from screener.models import CandidateResult, RunMetadata
from screener.scoring import AVOID_HIGH_RISK_TIER, BUY_REVIEW_TIER, WATCHLIST_TIER

_REVERSAL_REASON_HINTS = (
    "회복",
    "반전",
    "reclaim",
    "engulfing",
    "gap",
    "하단 꼬리 이후 종가가 일중 상단에서 마감",
    "실체가 커 매수 우위가 비교적 분명함",
    "inside day 안에서 매수 우위가 유지됨",
    "최근 2일 이상 종가 개선",
    "5일선 회복 또는 회복 시도",
    "gap 하락 이후 회복 흐름이 확인됨",
    "전일 몸통을 감싸는 bullish engulfing 유사 패턴",
)
_OVERSOLD_REASON_HINTS = ("BB 하단", "과매도", "저점", "재진입")
_EXTENDED_STATE_KEYS = {
    "last_score",
    "last_rank",
    "last_headline_reason",
    "last_headline_risk",
    "last_earnings_penalty",
    "last_volatility_penalty",
}
REGIME_QQQ_RETURN_THRESHOLD = -5.0
REGIME_WATCHLIST_CAP = 3


@dataclass(frozen=True)
class RegimeDecision:
    status: str
    is_bearish: bool
    watchlist_cap: int | None
    reason: str | None = None


def evaluate_regime_gate(
    *,
    qqq_above_20d_ma: bool | None,
    qqq_return_20d: float | None,
) -> RegimeDecision:
    if qqq_above_20d_ma is None or qqq_return_20d is None:
        return RegimeDecision(
            status="unknown",
            is_bearish=False,
            watchlist_cap=None,
            reason="missing_benchmark_context",
        )
    bearish = (not qqq_above_20d_ma) and (qqq_return_20d < REGIME_QQQ_RETURN_THRESHOLD)
    return RegimeDecision(
        status="capped" if bearish else "pass",
        is_bearish=bearish,
        watchlist_cap=REGIME_WATCHLIST_CAP if bearish else None,
        reason="bearish_qqq_regime" if bearish else "conditions_not_met",
    )


def _has_state_value(previous_state: dict[str, str | None], key: str) -> bool:
    return previous_state.get(key) is not None


def evaluate_daily_quality_gate(metadata: RunMetadata) -> str:
    if metadata.failed_ticker_count > 20 or metadata.bars_nonempty_count < 80 or metadata.latest_bar_date_mismatch_count > 10:
        return "block"
    if metadata.failed_ticker_count > 5 or metadata.latest_bar_date_mismatch_count > 0 or metadata.insufficient_history_count > 5:
        return "warn"
    return "pass"


def evaluate_intraday_quality_gate(
    *,
    collected_count: int,
    failed_count: int,
    skipped_due_to_credit_exhaustion_count: int,
) -> str:
    if collected_count < 20 or failed_count > 20 or skipped_due_to_credit_exhaustion_count > 0:
        return "block"
    if collected_count < 60 or failed_count > 5:
        return "warn"
    return "pass"


def headline_reason(candidate: CandidateResult) -> str:
    return candidate.reasons[0] if candidate.reasons else "n/a"


def headline_risk(candidate: CandidateResult) -> str:
    return candidate.risks[0] if candidate.risks else "n/a"


def material_signature(candidate: CandidateResult, *, rank: int) -> str:
    snapshot = candidate.indicator_snapshot or {}
    return "|".join(
        [
            str(candidate.score),
            str(rank),
            candidate.tier,
            headline_reason(candidate),
            headline_risk(candidate),
            str(snapshot.get("earnings_penalty", 0)),
            str(snapshot.get("volatility_penalty", 0)),
        ]
    )


def _has_compatible_material_signature(previous_signature: str | None, current_signature: str) -> bool:
    if previous_signature is None:
        return False
    return previous_signature.count("|") == current_signature.count("|")


def _has_single_reason_mix(candidate: CandidateResult) -> bool:
    reasons = candidate.reasons
    has_reversal_reason = any(
        any(hint in reason for hint in _REVERSAL_REASON_HINTS)
        for reason in reasons
    )
    has_oversold_or_bottom_reason = any(
        any(hint in reason for hint in _OVERSOLD_REASON_HINTS)
        for reason in reasons
    )
    return has_reversal_reason and has_oversold_or_bottom_reason


def _has_extended_previous_state(previous_state: dict[str, str | None]) -> bool:
    return any(_has_state_value(previous_state, key) for key in _EXTENDED_STATE_KEYS)


def determine_change_status(
    candidate: CandidateResult,
    *,
    rank: int,
    phase: str,
    previous_state: dict[str, str] | None,
) -> str:
    if previous_state is None:
        return "new"

    previous_tier = previous_state.get("last_delivery_tier")
    previous_score = int(previous_state.get("last_score", candidate.score) or candidate.score)
    previous_rank = int(previous_state.get("last_rank", rank) or rank)
    previous_headline_reason = previous_state.get("last_headline_reason")
    previous_headline_risk = previous_state.get("last_headline_risk")
    previous_earnings_penalty = int(previous_state.get("last_earnings_penalty", 0) or 0)
    previous_volatility_penalty = int(previous_state.get("last_volatility_penalty", 0) or 0)
    current_signature = material_signature(candidate, rank=rank)
    current_headline_reason = headline_reason(candidate)
    current_headline_risk = headline_risk(candidate)
    snapshot = candidate.indicator_snapshot or {}
    current_earnings_penalty = int(snapshot.get("earnings_penalty", 0) or 0)
    current_volatility_penalty = int(snapshot.get("volatility_penalty", 0) or 0)
    score_delta = abs(candidate.score - previous_score)
    rank_delta = abs(rank - previous_rank)
    has_extended_previous_state = _has_extended_previous_state(previous_state)

    if previous_tier == "digest" and rank <= 5 and candidate.score >= 60:
        return "upgraded"
    if score_delta >= 5 or rank_delta >= 2:
        return "material_change"
    if not has_extended_previous_state:
        return "unchanged"
    previous_signature = previous_state.get("last_material_signature")
    if _has_compatible_material_signature(previous_signature, current_signature) and previous_signature != current_signature:
        return "material_change"
    if _has_state_value(previous_state, "last_headline_reason") and previous_headline_reason != current_headline_reason:
        return "material_change"
    if _has_state_value(previous_state, "last_headline_risk") and previous_headline_risk != current_headline_risk:
        return "material_change"
    if _has_state_value(previous_state, "last_earnings_penalty") and previous_earnings_penalty != current_earnings_penalty:
        return "material_change"
    if _has_state_value(previous_state, "last_volatility_penalty") and previous_volatility_penalty != current_volatility_penalty:
        return "material_change"
    return "unchanged"


def classify_candidate(candidate: CandidateResult, *, rank: int, change_status: str) -> str:
    snapshot = candidate.indicator_snapshot or {}
    earnings_penalty = int(snapshot.get("earnings_penalty", 0) or 0)
    volatility_penalty = int(snapshot.get("volatility_penalty", 0) or 0)
    reason_count = len(candidate.reasons)

    if (
        candidate.tier == AVOID_HIGH_RISK_TIER
        or candidate.score < 45
        or reason_count < 2
        or earnings_penalty >= 8
        or (volatility_penalty >= 4 and candidate.score < 60)
    ):
        return "suppressed"
    if (
        candidate.tier == BUY_REVIEW_TIER
        and candidate.score >= 60
        and rank <= 5
        and change_status in {"new", "upgraded", "material_change"}
        and _has_single_reason_mix(candidate)
    ):
        return "single"
    if candidate.tier in {BUY_REVIEW_TIER, WATCHLIST_TIER} and rank <= 10:
        return "digest"
    return "suppressed"

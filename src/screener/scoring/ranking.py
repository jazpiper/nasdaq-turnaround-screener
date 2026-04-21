from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable


@dataclass(frozen=True)
class ScreenCandidate:
    ticker: str
    score: int
    subscores: dict[str, int]
    reasons: list[str]
    risks: list[str]
    snapshot: dict[str, Any]
    generated_at: str


def _clip(value: float, floor: float = 0.0, ceiling: float = 1.0) -> float:
    return max(floor, min(ceiling, value))


def _as_float(snapshot: dict[str, Any], key: str) -> float | None:
    value = snapshot.get(key)
    return None if value is None else float(value)


def has_minimum_history(snapshot: dict[str, Any], minimum_bars: int = 60) -> bool:
    return int(snapshot.get("bars_available", 0)) >= minimum_bars


def passes_liquidity(snapshot: dict[str, Any], minimum_average_volume: float = 1_000_000.0) -> bool:
    average_volume = _as_float(snapshot, "average_volume_20d")
    return average_volume is not None and average_volume >= minimum_average_volume


def near_lower_bollinger(snapshot: dict[str, Any], tolerance: float = 1.02) -> bool:
    close = _as_float(snapshot, "close")
    lower_bb = _as_float(snapshot, "bb_lower")
    intraday_low = _as_float(snapshot, "low")
    if close is None or lower_bb is None:
        return False
    return close <= lower_bb * tolerance or (intraday_low is not None and intraday_low <= lower_bb)


def near_recent_low(snapshot: dict[str, Any], max_distance_pct: float = 5.0) -> bool:
    distance_20d = _as_float(snapshot, "distance_to_20d_low")
    return distance_20d is not None and distance_20d <= max_distance_pct


def is_valid_snapshot(snapshot: dict[str, Any]) -> bool:
    required = ["close", "low", "bb_lower", "rsi_14", "distance_to_20d_low", "volume_ratio_20d"]
    return all(snapshot.get(key) is not None for key in required)


def filter_candidates(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for row in rows:
        if not is_valid_snapshot(row):
            continue
        if not has_minimum_history(row):
            continue
        if not passes_liquidity(row):
            continue
        if not near_lower_bollinger(row):
            continue
        if not near_recent_low(row):
            continue
        if bool(row.get("weekly_trend_severe_damage", False)):
            continue
        candidates.append(row)
    return candidates


def _score_oversold(snapshot: dict[str, Any], reasons: list[str]) -> int:
    close = _as_float(snapshot, "close") or 0.0
    lower_bb = _as_float(snapshot, "bb_lower") or close
    rsi_14 = _as_float(snapshot, "rsi_14") or 50.0
    band_distance = 0.0 if lower_bb == 0 else abs(close - lower_bb) / abs(lower_bb)
    proximity_score = _clip(1.0 - (band_distance / 0.03))
    rsi_score = _clip((35.0 - rsi_14) / 15.0)
    score = int(round((0.6 * proximity_score + 0.4 * rsi_score) * 25))
    if close <= lower_bb * 1.02:
        reasons.append("BB 하단 근처 또는 재진입 구간")
    if rsi_14 <= 35:
        reasons.append("RSI 14가 과매도권 또는 초기 탈출 구간")
    return score


def _score_bottom_context(snapshot: dict[str, Any], reasons: list[str]) -> int:
    distance_20 = _as_float(snapshot, "distance_to_20d_low") or 100.0
    distance_60 = _as_float(snapshot, "distance_to_60d_low") or 100.0
    score_20 = _clip(1.0 - (distance_20 / 8.0))
    score_60 = _clip(1.0 - (distance_60 / 15.0))
    score = int(round((0.6 * score_20 + 0.4 * score_60) * 20))
    if distance_20 <= 3.0:
        reasons.append("최근 20일 저점 부근")
    if distance_60 <= 8.0:
        reasons.append("중기 저점권과도 멀지 않음")
    return score


def _score_reversal(snapshot: dict[str, Any], reasons: list[str], risks: list[str]) -> int:
    close = _as_float(snapshot, "close") or 0.0
    sma_5 = _as_float(snapshot, "sma_5") or close
    close_streak = float(snapshot.get("close_improvement_streak", 0))
    rsi_slope = float(snapshot.get("rsi_3d_change", 0.0))
    below_sma_penalty = 0.0 if close >= sma_5 else 0.35
    streak_score = _clip(close_streak / 3.0)
    sma_score = 1.0 - below_sma_penalty
    rsi_score = _clip((rsi_slope + 6.0) / 12.0)
    raw = 0.45 * sma_score + 0.35 * streak_score + 0.20 * rsi_score
    score = int(round(_clip(raw) * 25))
    candle_bonus = 0

    close_location_value = _as_float(snapshot, "close_location_value")
    if close_location_value is not None:
        if close_location_value >= 0.7:
            candle_bonus += 2
            reasons.append("하단 꼬리 이후 종가가 일중 상단에서 마감")
        elif close_location_value <= 0.35:
            risks.append("종가가 일중 하단에 머물러 매수 우위 확인이 약함")

    lower_wick_ratio = _as_float(snapshot, "lower_wick_ratio")
    if lower_wick_ratio is not None and lower_wick_ratio >= 0.4:
        candle_bonus += 2

    if bool(snapshot.get("gap_down_reclaim", False)):
        candle_bonus += 3
        reasons.append("gap 하락 이후 회복 흐름이 확인됨")

    score = min(score + candle_bonus, 25)
    if close >= sma_5:
        reasons.append("5일선 회복 또는 회복 시도")
    else:
        risks.append("5일선 아래에 머물러 반전 확인이 약함")
    if close_streak >= 2:
        reasons.append("최근 2일 이상 종가 개선")
    return score


def _score_volume(snapshot: dict[str, Any], reasons: list[str], risks: list[str]) -> int:
    ratio = _as_float(snapshot, "volume_ratio_20d") or 0.0
    score = int(round(_clip((ratio - 0.8) / 0.8) * 15))
    if 0.8 <= ratio <= 1.4:
        reasons.append("거래량이 20일 평균 대비 과열되지 않음")
    elif ratio > 1.4:
        reasons.append("반등 시도에 거래량 유입이 동반됨")
    else:
        risks.append("거래량이 평균 대비 약해 신호 신뢰도가 낮을 수 있음")
    return score


def _score_market_context(snapshot: dict[str, Any], reasons: list[str], risks: list[str]) -> int:
    market_context = float(snapshot.get("market_context_score", 10.0))
    relative_strength_bonus = 0.0

    rel_strength_20d = _as_float(snapshot, "rel_strength_20d_vs_qqq")
    if rel_strength_20d is not None:
        if rel_strength_20d >= 5.0:
            relative_strength_bonus += 3.0
            reasons.append("최근 20일 기준 QQQ 대비 상대적으로 덜 약함")
        elif rel_strength_20d >= 2.0:
            relative_strength_bonus += 1.5
            reasons.append("시장 대비 상대강도가 개선되는 구간")
        elif rel_strength_20d <= -5.0:
            relative_strength_bonus -= 3.0
            risks.append("최근 20일 기준 시장 대비 상대약세가 큼")

    rel_strength_60d = _as_float(snapshot, "rel_strength_60d_vs_qqq")
    if rel_strength_60d is not None:
        if rel_strength_60d >= 4.0:
            relative_strength_bonus += 1.5
        elif rel_strength_60d <= -8.0:
            relative_strength_bonus -= 2.0
            risks.append("장세 반등 대비 추종력이 약할 수 있음")

    adjusted_context = market_context + relative_strength_bonus
    score = int(round(_clip(adjusted_context / 15.0) * 15))
    snapshot["relative_strength_score"] = score
    if float(snapshot.get("weekly_trend_penalty", 0.0)) >= 3.0:
        risks.append("주봉 추세가 아직 약해 강한 반전 확인이 더 필요함")
    if score <= 6:
        risks.append("시장/섹터 맥락 확인이 필요함")
    return score


def _apply_earnings_penalty(snapshot: dict[str, Any], risks: list[str]) -> int:
    penalty = 0
    days_to_next = snapshot.get("days_to_next_earnings")
    if days_to_next is not None:
        days_to_next = int(days_to_next)
        if days_to_next <= 2:
            penalty = max(penalty, 8)
            risks.append("실적 발표가 임박해 이벤트 리스크가 큼")
        elif days_to_next <= 5:
            penalty = max(penalty, 4)
            risks.append("실적 발표가 가까워 변동성 리스크가 있음")

    days_since_last = snapshot.get("days_since_last_earnings")
    if days_since_last is not None and int(days_since_last) <= 2:
        penalty = max(penalty, 3)
        risks.append("실적 발표 직후 변동성 구간일 수 있음")

    return penalty


def _apply_volatility_penalty(snapshot: dict[str, Any], reasons: list[str], risks: list[str]) -> int:
    penalty = 0
    calm_signals = 0

    atr_14_pct = _as_float(snapshot, "atr_14_pct")
    if atr_14_pct is not None:
        if atr_14_pct >= 6.0:
            penalty = max(penalty, 4)
            risks.append("변동성이 아직 높아 바닥 확인이 이를 수 있음")
        elif atr_14_pct <= 3.5:
            calm_signals += 1

    daily_range_pct = _as_float(snapshot, "daily_range_pct")
    if daily_range_pct is not None:
        if daily_range_pct >= 7.0:
            penalty = max(penalty, 2)
            risks.append("일중 range가 커서 신호 품질이 불안정함")
        elif daily_range_pct <= 4.5:
            calm_signals += 1

    bb_width_pct = _as_float(snapshot, "bb_width_pct")
    if bb_width_pct is not None:
        if bb_width_pct >= 25.0:
            penalty = max(penalty, 3)
            risks.append("볼린저 밴드 폭이 넓어 아직 구조가 불안정함")
        elif bb_width_pct <= 18.0:
            calm_signals += 1

    if penalty == 0 and calm_signals == 3:
        reasons.append("변동성 과열 없이 반등 시도가 나타남")

    return penalty


def score_candidate(snapshot: dict[str, Any]) -> ScreenCandidate:
    working_snapshot = dict(snapshot)
    reasons: list[str] = []
    risks: list[str] = []
    subscores = {
        "oversold": _score_oversold(working_snapshot, reasons),
        "bottom_context": _score_bottom_context(working_snapshot, reasons),
        "reversal": _score_reversal(working_snapshot, reasons, risks),
        "volume": _score_volume(working_snapshot, reasons, risks),
        "market_context": _score_market_context(working_snapshot, reasons, risks),
    }
    earnings_penalty = _apply_earnings_penalty(working_snapshot, risks)
    volatility_penalty = _apply_volatility_penalty(working_snapshot, reasons, risks)
    working_snapshot["earnings_penalty"] = earnings_penalty
    working_snapshot["volatility_penalty"] = volatility_penalty
    score = max(sum(subscores.values()) - earnings_penalty - volatility_penalty, 0)
    if (_as_float(working_snapshot, "sma_20") or 0.0) < (_as_float(working_snapshot, "sma_60") or 0.0):
        risks.append("중기 추세는 아직 하락 압력일 수 있음")
    return ScreenCandidate(
        ticker=str(working_snapshot["ticker"]),
        score=score,
        subscores=subscores,
        reasons=list(dict.fromkeys(reasons)),
        risks=list(dict.fromkeys(risks)),
        snapshot=working_snapshot,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )


def rank_candidates(rows: Iterable[dict[str, Any]]) -> list[ScreenCandidate]:
    scored = [score_candidate(row) for row in filter_candidates(rows)]
    return sorted(scored, key=lambda candidate: (-candidate.score, candidate.ticker))

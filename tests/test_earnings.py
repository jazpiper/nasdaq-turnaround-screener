from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from screener.data.earnings import FileBackedEarningsCalendarProvider
from screener.scoring.ranking import score_candidate


def test_file_backed_earnings_provider_computes_day_offsets(tmp_path: Path) -> None:
    path = tmp_path / "earnings-calendar.json"
    path.write_text(
        json.dumps(
            {
                "AAPL": {
                    "next_earnings_date": "2026-04-25",
                    "last_earnings_date": "2026-01-30"
                },
                "MSFT": {
                    "days_to_next_earnings": 8,
                    "days_since_last_earnings": 80
                }
            }
        ),
        encoding="utf-8",
    )

    provider = FileBackedEarningsCalendarProvider(path)
    result = provider.fetch(["AAPL", "MSFT", "NVDA"], date(2026, 4, 21))

    assert result["AAPL"].days_to_next_earnings == 4
    assert result["AAPL"].days_since_last_earnings == 81
    assert result["MSFT"].days_to_next_earnings == 8
    assert "NVDA" not in result


def test_score_candidate_applies_earnings_penalty_and_risk() -> None:
    candidate = score_candidate(
        {
            "ticker": "AAPL",
            "bars_available": 90,
            "average_volume_20d": 2_000_000,
            "close": 100.0,
            "low": 98.0,
            "bb_lower": 99.0,
            "rsi_14": 30.0,
            "distance_to_20d_low": 1.0,
            "distance_to_60d_low": 4.0,
            "sma_5": 99.5,
            "sma_20": 101.0,
            "sma_60": 100.0,
            "volume_ratio_20d": 1.0,
            "close_improvement_streak": 2,
            "rsi_3d_change": 2.0,
            "market_context_score": 10.0,
            "weekly_trend_penalty": 0.0,
            "weekly_trend_severe_damage": False,
            "days_to_next_earnings": 1,
            "days_since_last_earnings": 40,
        }
    )

    assert candidate.snapshot["earnings_penalty"] == 8
    assert "실적 발표가 임박해 이벤트 리스크가 큼" in candidate.risks
    assert candidate.score < sum(candidate.subscores.values())


def test_score_candidate_applies_volatility_penalty_and_risks() -> None:
    candidate = score_candidate(
        {
            "ticker": "AAPL",
            "bars_available": 90,
            "average_volume_20d": 2_000_000,
            "close": 100.0,
            "low": 98.0,
            "bb_lower": 99.0,
            "rsi_14": 30.0,
            "distance_to_20d_low": 1.0,
            "distance_to_60d_low": 4.0,
            "sma_5": 99.5,
            "sma_20": 101.0,
            "sma_60": 100.0,
            "volume_ratio_20d": 1.0,
            "close_improvement_streak": 2,
            "rsi_3d_change": 2.0,
            "market_context_score": 10.0,
            "weekly_trend_penalty": 0.0,
            "weekly_trend_severe_damage": False,
            "atr_14_pct": 6.4,
            "daily_range_pct": 7.2,
            "bb_width_pct": 26.0,
        }
    )

    assert candidate.snapshot["volatility_penalty"] == 4
    assert "변동성이 아직 높아 바닥 확인이 이를 수 있음" in candidate.risks
    assert "일중 range가 커서 신호 품질이 불안정함" in candidate.risks
    assert "볼린저 밴드 폭이 넓어 아직 구조가 불안정함" in candidate.risks
    assert candidate.score == sum(candidate.subscores.values()) - 4


def test_score_candidate_applies_candle_reversal_bonus_and_reason() -> None:
    candidate = score_candidate(
        {
            "ticker": "AAPL",
            "bars_available": 90,
            "average_volume_20d": 2_000_000,
            "close": 100.0,
            "low": 95.0,
            "bb_lower": 99.0,
            "rsi_14": 30.0,
            "distance_to_20d_low": 1.0,
            "distance_to_60d_low": 4.0,
            "sma_5": 99.5,
            "sma_20": 101.0,
            "sma_60": 100.0,
            "volume_ratio_20d": 1.0,
            "close_improvement_streak": 2,
            "rsi_3d_change": 2.0,
            "market_context_score": 10.0,
            "weekly_trend_penalty": 0.0,
            "weekly_trend_severe_damage": False,
            "close_above_open": True,
            "close_location_value": 0.85,
            "lower_wick_ratio": 0.45,
            "upper_wick_ratio": 0.1,
            "real_body_pct": 0.45,
            "gap_down_pct": -2.0,
            "gap_down_reclaim": True,
            "inside_day": True,
            "bullish_engulfing_like": True,
        }
    )

    assert "하단 꼬리 이후 종가가 일중 상단에서 마감" in candidate.reasons
    assert "gap 하락 이후 회복 흐름이 확인됨" in candidate.reasons
    assert "실체가 커 매수 우위가 비교적 분명함" in candidate.reasons
    assert "inside day 안에서 매수 우위가 유지됨" in candidate.reasons
    assert "전일 몸통을 감싸는 bullish engulfing 유사 패턴" in candidate.reasons
    assert candidate.subscores["reversal"] == 25


def test_score_candidate_adds_candle_structure_risk_when_close_is_weak() -> None:
    candidate = score_candidate(
        {
            "ticker": "AAPL",
            "bars_available": 90,
            "average_volume_20d": 2_000_000,
            "close": 100.0,
            "low": 95.0,
            "bb_lower": 99.0,
            "rsi_14": 30.0,
            "distance_to_20d_low": 1.0,
            "distance_to_60d_low": 4.0,
            "sma_5": 101.0,
            "sma_20": 101.0,
            "sma_60": 100.0,
            "volume_ratio_20d": 1.0,
            "close_improvement_streak": 0,
            "rsi_3d_change": -1.0,
            "market_context_score": 10.0,
            "weekly_trend_penalty": 0.0,
            "weekly_trend_severe_damage": False,
            "close_above_open": False,
            "close_location_value": 0.2,
            "lower_wick_ratio": 0.1,
            "upper_wick_ratio": 0.5,
            "real_body_pct": 0.12,
            "gap_down_pct": 0.5,
            "gap_down_reclaim": False,
            "inside_day": False,
            "bullish_engulfing_like": False,
        }
    )

    assert "종가가 일중 하단에 머물러 매수 우위 확인이 약함" in candidate.risks
    assert "상단 꼬리가 길어 추격 매수 실패 가능성이 남아 있음" in candidate.risks

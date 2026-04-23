import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from screener.scoring.ranking import rank_candidates, score_candidate


def make_snapshot(ticker: str, **overrides):
    snapshot = {
        "ticker": ticker,
        "close": 98.0,
        "low": 96.5,
        "bb_lower": 97.0,
        "rsi_14": 31.0,
        "distance_to_20d_low": 2.0,
        "distance_to_60d_low": 4.0,
        "volume_ratio_20d": 1.1,
        "average_volume_20d": 2_500_000.0,
        "bars_available": 90,
        "sma_5": 97.5,
        "sma_20": 100.0,
        "sma_60": 104.0,
        "close_improvement_streak": 2,
        "rsi_3d_change": 4.0,
        "market_context_score": 10.0,
        "weekly_trend_severe_damage": False,
        "weekly_trend_penalty": 0.0,
        "atr_14_pct": 2.8,
        "daily_range_pct": 3.2,
        "bb_width_pct": 12.0,
        "close_above_open": True,
        "real_body_pct": 0.4,
        "close_location_value": 0.8,
        "lower_wick_ratio": 0.45,
        "upper_wick_ratio": 0.1,
        "inside_day": False,
        "bullish_engulfing_like": False,
        "gap_down_reclaim": False,
    }
    snapshot.update(overrides)
    return snapshot


class ScoringInvariantTests(unittest.TestCase):
    def test_earnings_penalty_uses_max_within_overlay(self):
        imminent_only = score_candidate(
            make_snapshot(
                "IMMINENT_ONLY",
                days_to_next_earnings=2,
            )
        )
        imminent_and_recent = score_candidate(
            make_snapshot(
                "IMMINENT_AND_RECENT",
                days_to_next_earnings=2,
                days_since_last_earnings=2,
            )
        )

        self.assertEqual(imminent_only.snapshot["earnings_penalty"], 8)
        self.assertEqual(imminent_and_recent.snapshot["earnings_penalty"], 8)
        self.assertEqual(imminent_only.score, imminent_and_recent.score)
        self.assertIn("실적 발표 직후 변동성 구간일 수 있음", imminent_and_recent.risks)

    def test_volatility_penalty_uses_max_within_overlay(self):
        atr_only = score_candidate(
            make_snapshot(
                "ATR_ONLY",
                atr_14_pct=6.2,
                daily_range_pct=4.0,
                bb_width_pct=18.0,
            )
        )
        all_volatility_triggers = score_candidate(
            make_snapshot(
                "ALL_VOL",
                atr_14_pct=6.2,
                daily_range_pct=7.1,
                bb_width_pct=26.0,
            )
        )

        self.assertEqual(atr_only.snapshot["volatility_penalty"], 4)
        self.assertEqual(all_volatility_triggers.snapshot["volatility_penalty"], 4)
        self.assertEqual(atr_only.score, all_volatility_triggers.score)
        self.assertIn("일중 range가 커서 신호 품질이 불안정함", all_volatility_triggers.risks)
        self.assertIn("볼린저 밴드 폭이 넓어 아직 구조가 불안정함", all_volatility_triggers.risks)

    def test_rank_candidates_breaks_ties_by_ticker(self):
        ranked = rank_candidates(
            [
                make_snapshot("MSFT"),
                make_snapshot("AAPL"),
            ]
        )

        self.assertEqual(ranked[0].score, ranked[1].score)
        self.assertEqual([candidate.ticker for candidate in ranked], ["AAPL", "MSFT"])

    def test_score_candidate_overwrites_relative_strength_score_with_market_context_subscore(self):
        candidate = score_candidate(
            make_snapshot(
                "RELSTR",
                relative_strength_score=999,
                market_context_score=10.0,
                rel_strength_20d_vs_qqq=5.5,
                rel_strength_60d_vs_qqq=4.5,
            )
        )

        self.assertEqual(candidate.snapshot["relative_strength_score"], candidate.subscores["market_context"])
        self.assertNotEqual(candidate.snapshot["relative_strength_score"], 999)

    def test_rank_candidates_filters_out_zero_score_after_penalties(self):
        zero_score_candidate = make_snapshot(
            "ZERO",
            close=110.0,
            low=96.0,
            days_to_next_earnings=2,
            atr_14_pct=6.5,
            daily_range_pct=7.5,
            bb_width_pct=26.0,
            sma_5=120.0,
            close_improvement_streak=0,
            rsi_3d_change=-6.0,
            rsi_14=50.0,
            distance_to_20d_low=12.5,
            distance_to_60d_low=100.0,
            volume_ratio_20d=0.1,
            market_context_score=0.0,
            weekly_trend_penalty=6.0,
            rel_strength_20d_vs_qqq=-6.0,
            rel_strength_60d_vs_qqq=-9.0,
            close_above_open=False,
            real_body_pct=0.1,
            close_location_value=0.2,
            lower_wick_ratio=0.0,
            upper_wick_ratio=0.5,
            inside_day=False,
            bullish_engulfing_like=False,
            gap_down_reclaim=False,
        )
        healthy_candidate = make_snapshot("HEALTHY")

        scored_zero = score_candidate(zero_score_candidate)
        self.assertEqual(scored_zero.score, 0)

        ranked = rank_candidates([zero_score_candidate, healthy_candidate])
        self.assertEqual([candidate.ticker for candidate in ranked], ["HEALTHY"])


if __name__ == "__main__":
    unittest.main()

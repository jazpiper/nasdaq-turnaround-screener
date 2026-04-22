import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from screener.scoring.ranking import filter_candidates, rank_candidates


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
    }
    snapshot.update(overrides)
    return snapshot


class ScoringTests(unittest.TestCase):
    def test_filter_candidates_accepts_valid_candidate(self):
        rows = [make_snapshot("AAPL")]
        filtered = filter_candidates(rows)
        self.assertEqual(len(filtered), 1)

    def test_filter_candidates_rejects_insufficient_liquidity(self):
        rows = [make_snapshot("AAPL", average_volume_20d=100_000.0)]
        self.assertEqual(filter_candidates(rows), [])
    def test_filter_candidates_rejects_severely_broken_weekly_trend(self):
        rows = [make_snapshot("AAPL", weekly_trend_severe_damage=True)]
        self.assertEqual(filter_candidates(rows), [])


    def test_rank_candidates_orders_by_score(self):
        rows = [
            make_snapshot("STRONG", close=97.0, bb_lower=97.5, rsi_14=27.0, volume_ratio_20d=1.4, close_improvement_streak=3),
            make_snapshot("WEAKER", close=98.5, bb_lower=97.0, rsi_14=34.0, volume_ratio_20d=0.9, close_improvement_streak=1),
        ]
        ranked = rank_candidates(rows)
        self.assertEqual([candidate.ticker for candidate in ranked], ["STRONG", "WEAKER"])
        self.assertGreater(ranked[0].score, ranked[1].score)
        self.assertIn("BB 하단 근처 또는 재진입 구간", ranked[0].reasons)

    def test_rank_candidates_attaches_risks(self):
        candidate = rank_candidates([
            make_snapshot("RISKY", sma_5=101.0, close=98.0, volume_ratio_20d=0.6, market_context_score=4.0)
        ])[0]
        self.assertTrue(any("거래량" in risk for risk in candidate.risks))
        self.assertTrue(any("시장/섹터" in risk for risk in candidate.risks))

    def test_rank_candidates_adds_weekly_trend_risk_when_penalized(self):
        candidate = rank_candidates([
            make_snapshot("WEEKLY", weekly_trend_penalty=6.0, market_context_score=4.0)
        ])[0]
        self.assertTrue(any("주봉 추세" in risk for risk in candidate.risks))

    def test_rank_candidates_excludes_zero_score_candidates(self):
        ranked = rank_candidates([
            make_snapshot(
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
                distance_to_20d_low=5.0,
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
        ])
        self.assertEqual(ranked, [])


if __name__ == "__main__":
    unittest.main()

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


if __name__ == "__main__":
    unittest.main()

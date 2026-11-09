import os
import tempfile
import unittest

from app.agents.analysis_agent import AnalysisAgent
from app.models.market import MarketSnapshot, TradingPair
from app.services.market_history import MarketHistory
from app.services.state_store import JsonStateStore


class AnalysisAgentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        store = JsonStateStore(path=os.path.join(self.tmp.name, "history.json"))
        self.history = MarketHistory(store=store)
        self.agent = AnalysisAgent(self.history)
        self.start = 1_700_000_000.0

    def tearDown(self):
        self.tmp.cleanup()

    def snapshot(self, price, change=-3.0):
        return MarketSnapshot(
            pairs=[TradingPair(base_symbol="VVV", quote_symbol="USDC", price=price,
                               change_24h=change, volume_24h=1_000_000)]
        )

    def test_stop_loss_exits_the_full_position(self):
        recommendations = self.agent.analyze(
            self.snapshot(price=9.0, change=-10.0),
            {"VVV": {"avg_entry": 10.0, "buy_step": 1}},
            {"VVV": 100.0},
        )
        self.assertEqual(len(recommendations), 1)
        rec = recommendations[0]
        self.assertEqual(rec.action, "sell")
        self.assertEqual(rec.exit_kind, "stop_loss")
        self.assertAlmostEqual(rec.sell_fraction, 1.0)

    def test_first_take_profit_rung_sells_twenty_percent_of_remaining(self):
        recommendations = self.agent.analyze(
            self.snapshot(price=10.2, change=2.0),
            {"VVV": {"avg_entry": 10.0, "buy_step": 1}},
            {"VVV": 100.0},
        )
        rec = recommendations[0]
        self.assertEqual(rec.exit_kind, "take_profit")
        self.assertAlmostEqual(rec.sell_fraction, 0.20)

    def test_ladder_does_not_repeat_a_rung(self):
        recommendations = self.agent.analyze(
            self.snapshot(price=10.2, change=2.0),
            {"VVV": {"avg_entry": 10.0, "buy_step": 1, "cumulative_sold": 0.20}},
            {"VVV": 80.0},
        )
        # +2% with T1 already sold -> no new rung until +3%.
        self.assertEqual(recommendations, [])

    def test_trailing_stop_protects_a_runner(self):
        recommendations = self.agent.analyze(
            self.snapshot(price=10.3, change=3.0),
            {"VVV": {"avg_entry": 10.0, "buy_step": 1, "peak_price": 10.5}},
            {"VVV": 10.0},
        )
        rec = recommendations[0]
        self.assertEqual(rec.exit_kind, "trailing_stop")
        self.assertAlmostEqual(rec.sell_fraction, 1.0)

    def feed_decline(self, extra_volume=1000.0):
        cumulative = 0.0
        for index in range(25):
            cumulative += 1000.0
            price = 1.30 - index * 0.01
            self.history.record_pair(
                "VVV", price, cumulative, now=self.start + index * 60
            )
        for index in range(5):
            cumulative += extra_volume
            self.history.record_pair(
                "VVV", 1.05, cumulative, now=self.start + (25 + index) * 60
            )

    def test_buy_blocked_without_volume_spike(self):
        self.feed_decline(extra_volume=500.0)
        recommendations = self.agent.analyze(self.snapshot(1.05, -3.0), {}, {})
        self.assertEqual(recommendations, [])

    def test_buy_allowed_when_dip_vwap_rsi_and_volume_align(self):
        self.feed_decline(extra_volume=6000.0)
        recommendations = self.agent.analyze(self.snapshot(1.05, -3.0), {}, {})
        self.assertEqual(len(recommendations), 1)
        rec = recommendations[0]
        self.assertEqual(rec.action, "buy")
        self.assertEqual(rec.buy_step, 1)
        self.assertTrue(rec.volume_spike)
        self.assertLess(rec.rsi, 35)

    def test_reentry_is_blocked_after_a_stop_loss(self):
        import time

        self.feed_decline(extra_volume=6000.0)
        recommendations = self.agent.analyze(
            self.snapshot(1.05, -3.0),
            {"VVV": {"avg_entry": 0.0, "buy_step": 0,
                     "last_exit_kind": "stop_loss",
                     "last_exit_price": 1.06,
                     "last_exit_ts": time.time() - 60}},
            {},
        )
        self.assertEqual(recommendations, [])


if __name__ == "__main__":
    unittest.main()

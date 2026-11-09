import os
import tempfile
import unittest

from app.services.demo_portfolio import DemoPortfolio, STARTING_CASH
from app.services.state_store import JsonStateStore


class FakeProposal:
    def __init__(self, token, action, amount, price):
        self.token = token
        self.action = action
        self.amount = amount
        self.price = price


class DemoPortfolioTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.store = JsonStateStore(
            path=os.path.join(self.directory.name, "demo_portfolio.json")
        )
        self.portfolio = DemoPortfolio(store=self.store)

    def test_starts_with_the_configured_cash_and_no_positions(self):
        self.assertEqual(self.portfolio.cash, STARTING_CASH)
        self.assertEqual(self.portfolio.positions, {})
        summary = self.portfolio.summary()
        self.assertEqual(summary["equity"], STARTING_CASH)
        self.assertEqual(summary["pnl_usd"], 0.0)
        self.assertEqual(summary["fills"], 0)

    def test_buy_reduces_cash_and_records_a_position(self):
        fill = self.portfolio.apply_fill(FakeProposal("VVV", "buy", 10.0, 25.0))
        self.assertIsNotNone(fill)
        self.assertEqual(fill["value_usd"], 250.0)
        self.assertAlmostEqual(self.portfolio.cash, 750.0)
        self.assertAlmostEqual(self.portfolio.positions["VVV"]["qty"], 10.0)
        self.assertAlmostEqual(self.portfolio.positions["VVV"]["avg_entry"], 25.0)
        self.assertTrue(fill["tx_hash"].startswith("demo-"))

    def test_second_buy_updates_the_average_entry(self):
        self.portfolio.apply_fill(FakeProposal("VVV", "buy", 10.0, 20.0))
        self.portfolio.apply_fill(FakeProposal("VVV", "buy", 10.0, 30.0))
        self.assertAlmostEqual(self.portfolio.positions["VVV"]["avg_entry"], 25.0)
        self.assertAlmostEqual(self.portfolio.positions["VVV"]["qty"], 20.0)

    def test_buy_is_clipped_to_available_cash(self):
        fill = self.portfolio.apply_fill(FakeProposal("VVV", "buy", 1000.0, 10.0))
        self.assertAlmostEqual(fill["quantity"], 100.0)
        self.assertAlmostEqual(self.portfolio.cash, 0.0)
        self.assertAlmostEqual(self.portfolio.positions["VVV"]["qty"], 100.0)

    def test_sell_returns_cash_and_clears_the_position(self):
        self.portfolio.apply_fill(FakeProposal("VVV", "buy", 10.0, 20.0))
        fill = self.portfolio.apply_fill(FakeProposal("VVV", "sell", 10.0, 30.0))
        self.assertAlmostEqual(fill["value_usd"], 300.0)
        self.assertAlmostEqual(self.portfolio.cash, 1100.0)
        self.assertNotIn("VVV", self.portfolio.positions)
        self.assertEqual(len(self.portfolio.fills), 2)

    def test_sell_without_holdings_is_rejected(self):
        self.assertIsNone(self.portfolio.apply_fill(FakeProposal("VVV", "sell", 1.0, 10.0)))
        self.assertEqual(len(self.portfolio.fills), 0)

    def test_invalid_proposals_are_rejected(self):
        self.assertIsNone(self.portfolio.apply_fill(FakeProposal("VVV", "buy", 0.0, 10.0)))
        self.assertIsNone(self.portfolio.apply_fill(FakeProposal("VVV", "buy", 1.0, 0.0)))
        self.assertIsNone(self.portfolio.apply_fill(FakeProposal("", "buy", 1.0, 10.0)))

    def test_state_survives_a_restart(self):
        self.portfolio.apply_fill(FakeProposal("AERO", "buy", 100.0, 2.0))
        restored = DemoPortfolio(store=self.store)
        self.assertAlmostEqual(restored.cash, self.portfolio.cash)
        self.assertAlmostEqual(restored.positions["AERO"]["qty"], 100.0)
        self.assertEqual(len(restored.fills), 1)

    def test_holdings_include_cash_as_usdc(self):
        self.portfolio.apply_fill(FakeProposal("AERO", "buy", 100.0, 2.0))
        holdings = self.portfolio.holdings()
        self.assertAlmostEqual(holdings["AERO"], 100.0)
        self.assertAlmostEqual(holdings["USDC"], 800.0)

    def test_summary_marks_unrealised_profit(self):
        self.portfolio.apply_fill(FakeProposal("AERO", "buy", 100.0, 2.0))
        summary = self.portfolio.summary({"AERO": 3.0})
        self.assertAlmostEqual(summary["equity"], 1100.0)
        self.assertAlmostEqual(summary["pnl_usd"], 100.0)
        self.assertAlmostEqual(summary["positions"][0]["unrealized_usd"], 100.0)

    def test_reset_restores_the_starting_state(self):
        self.portfolio.apply_fill(FakeProposal("AERO", "buy", 100.0, 2.0))
        summary = self.portfolio.reset()
        self.assertEqual(summary["cash"], STARTING_CASH)
        self.assertEqual(summary["positions"], [])
        self.assertEqual(summary["fills"], 0)


if __name__ == "__main__":
    unittest.main()

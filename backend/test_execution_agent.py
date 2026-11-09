import unittest

from app.agents.execution_agent import ExecutionAgent
from app.models.agents import AnalysisRecommendation, RiskAssessment


def risk(max_notional=80.0):
    return RiskAssessment(
        approved=True,
        reason="ok",
        max_slippage=0.5,
        estimated_gas_usd=0.01,
        expected_profit_usd=1.2,
        max_notional_usd=max_notional,
    )


def buy(step=1, token="VVV"):
    return AnalysisRecommendation(
        token=token, action="buy", confidence=0.7, reason="Dip",
        price=2.0, pct_change=-3.0, buy_step=step,
    )


def sell(fraction=0.2, token="VVV"):
    return AnalysisRecommendation(
        token=token, action="sell", confidence=0.9, reason="Profit",
        price=2.0, pct_change=3.0, sell_fraction=fraction, gain_pct=0.02,
        exit_kind="take_profit",
    )


class ExecutionAgentTests(unittest.TestCase):
    def setUp(self):
        self.agent = ExecutionAgent()

    def test_no_fake_holdings_means_no_buy(self):
        proposal = self.agent.create_proposal(buy(), risk(), {}, {"ETH": 3000.0})
        self.assertEqual(proposal.status, "rejected")
        self.assertEqual(proposal.amount, 0.0)
        self.assertIn("Insufficient buying power", proposal.reason)

    def test_fourth_buy_step_sizes_at_sixty_percent(self):
        proposal = self.agent.create_proposal(
            buy(step=4), risk(), {"USDC": 1000.0}, {"ETH": 3000.0}
        )
        # target 8% of $1000 = $80; step 4 = 60% -> $48 -> 24 tokens at $2
        self.assertEqual(proposal.status, "pending")
        self.assertAlmostEqual(proposal.notional_usd, 48.0, places=2)
        self.assertAlmostEqual(proposal.amount, 24.0, places=6)

    def test_sizing_respects_risk_headroom(self):
        proposal = self.agent.create_proposal(
            buy(step=4), risk(max_notional=10.0), {"USDC": 1000.0}, {"ETH": 3000.0}
        )
        self.assertAlmostEqual(proposal.notional_usd, 10.0, places=2)

    def test_sell_uses_analysis_fraction(self):
        proposal = self.agent.create_proposal(
            sell(0.2), risk(), {"VVV": 100.0}, {"ETH": 3000.0}
        )
        self.assertEqual(proposal.status, "pending")
        self.assertAlmostEqual(proposal.amount, 20.0, places=6)
        self.assertAlmostEqual(proposal.notional_usd, 40.0, places=2)

    def test_sell_without_holdings_is_rejected(self):
        proposal = self.agent.create_proposal(sell(), risk(), {}, {"ETH": 3000.0})
        self.assertEqual(proposal.status, "rejected")
        self.assertIn("No VVV holdings", proposal.reason)

    def test_auto_tradeable_flag_matches_policy(self):
        vvv = self.agent.create_proposal(buy(), risk(), {"USDC": 1000.0}, {})
        shib = self.agent.create_proposal(buy(token="SHIB"), risk(), {"USDC": 1000.0}, {})
        self.assertTrue(vvv.auto_tradeable)
        self.assertFalse(shib.auto_tradeable)


if __name__ == "__main__":
    unittest.main()

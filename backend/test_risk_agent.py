import unittest

from app.agents.risk_agent import RiskAgent
from app.models.agents import AnalysisRecommendation
from app.services.guardrails import Guardrails


def buy(**overrides):
    values = dict(
        token="VVV",
        action="buy",
        confidence=0.7,
        reason="Dip",
        price=2.0,
        pct_change=-3.0,
        buy_step=1,
    )
    values.update(overrides)
    return AnalysisRecommendation(**values)


def sell(**overrides):
    values = dict(
        token="VVV",
        action="sell",
        confidence=0.9,
        reason="Profit",
        price=2.0,
        pct_change=3.0,
        sell_fraction=0.25,
        gain_pct=0.03,
        exit_kind="take_profit",
    )
    values.update(overrides)
    return AnalysisRecommendation(**values)


class RiskAgentTests(unittest.TestCase):
    def setUp(self):
        self.agent = RiskAgent()

    def validate(self, rec, holdings=None, portfolio=1000.0, cash=1000.0, gas=0.01, rails=None):
        return self.agent.validate(
            rec,
            holdings or {},
            market_prices={"ETH": 3000.0},
            gas_gwei=gas,
            portfolio_value=portfolio,
            guardrails=rails or Guardrails(),
            available_cash=cash,
        )

    def test_buy_is_sized_and_approved(self):
        result = self.validate(buy())
        self.assertTrue(result.approved, result.reason)
        self.assertAlmostEqual(result.max_notional_usd, 80.0, places=2)
        self.assertGreater(result.expected_profit_usd, 0.10)
        self.assertTrue(all(check["ok"] for check in result.checks))

    def test_gas_cap_blocks(self):
        result = self.validate(buy(), gas=60.0)
        self.assertFalse(result.approved)
        self.assertIn("exceeds", result.reason)

    def test_kill_switch_blocks(self):
        rails = Guardrails()
        rails.halt("test kill switch")
        result = self.validate(buy(), rails=rails)
        self.assertFalse(result.approved)
        self.assertIn("halted", result.reason.lower())

    def test_position_cap_blocks_when_headroom_is_exhausted(self):
        result = self.validate(buy(), holdings={"VVV": 50.0})  # $100 = 10% cap
        self.assertFalse(result.approved)
        self.assertIn("Position cap", result.reason)

    def test_min_profit_blocks_dust_sized_trades(self):
        result = self.validate(buy(), portfolio=50.0, cash=50.0)
        self.assertFalse(result.approved)
        self.assertIn("Expected profit", result.reason)

    def test_sell_without_holdings_is_rejected(self):
        result = self.validate(sell())
        self.assertFalse(result.approved)
        self.assertIn("no holdings", result.reason.lower())

    def test_stop_loss_is_exempt_from_min_profit(self):
        result = self.validate(
            sell(sell_fraction=1.0, gain_pct=-0.06, exit_kind="stop_loss"),
            holdings={"VVV": 10.0},
            portfolio=20.0,
        )
        self.assertTrue(result.approved, result.reason)
        self.assertTrue(
            any(check["check"] == "min_profit" and "exempt" in check["detail"]
                for check in result.checks)
        )

    def test_dynamic_slippage_scales_with_volatility(self):
        calm = self.validate(buy(pct_change=-1.0)).max_slippage
        volatile = self.validate(buy(pct_change=-12.0)).max_slippage
        self.assertAlmostEqual(calm, 0.5)
        self.assertGreater(volatile, calm)


if __name__ == "__main__":
    unittest.main()

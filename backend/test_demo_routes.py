import os
import tempfile
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import routes_portfolio
from app.models.agents import TradeProposal
from app.services.demo_portfolio import DemoPortfolio
from app.services.state_store import JsonStateStore


class DemoRouteTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        store = JsonStateStore(
            path=os.path.join(self.directory.name, "demo_portfolio.json")
        )
        self.portfolio = DemoPortfolio(store=store)

        # A stand-in controller that behaves like the demo singleton.
        self.controller = routes_portfolio.controller
        self.original = (
            self.controller.demo,
            self.controller.demo_portfolio,
            list(self.controller.proposals),
            dict(self.controller.position_states),
            dict(self.controller.simulated_positions),
            dict(self.controller.user_holdings),
            self.controller.guardrails.to_dict(),
            dict(self.controller.last_trade_times),
        )
        self.controller.demo = True
        self.controller.demo_portfolio = self.portfolio
        self.controller.proposals = []
        self.controller.position_states = {}
        self.controller.simulated_positions = {}
        self.controller.user_holdings = self.portfolio.holdings()

        app = FastAPI()
        app.include_router(routes_portfolio.router, prefix="/portfolio")
        self.client = TestClient(app)

    def tearDown(self):
        from app.services.guardrails import Guardrails

        (
            self.controller.demo,
            self.controller.demo_portfolio,
            self.controller.proposals,
            self.controller.position_states,
            self.controller.simulated_positions,
            self.controller.user_holdings,
            guardrail_state,
            last_trade_times,
        ) = self.original
        self.controller.guardrails = Guardrails.from_dict(guardrail_state)
        self.controller.last_trade_times = last_trade_times

    def _proposal(self):
        return TradeProposal(
            id="demo-1",
            token="AERO",
            action="buy",
            amount=100.0,
            price=2.0,
            reason="test",
            slippage=0.5,
            gas_limit=250_000,
            timestamp=1_700_000_000,
        )

    def test_demo_summary_endpoint(self):
        response = self.client.get("/portfolio/demo")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["cash"], 1000.0)
        self.assertEqual(body["positions"], [])
        self.assertEqual(body["fills"], 0)

    def test_demo_endpoint_is_404_outside_demo_mode(self):
        self.controller.demo = False
        self.controller.demo_portfolio = None
        response = self.client.get("/portfolio/demo")
        self.assertEqual(response.status_code, 404)

    def test_recording_a_real_trade_is_blocked(self):
        response = self.client.post(
            "/portfolio/trade",
            json={
                "tx_hash": "0xabc",
                "network": "base",
                "pair": "AERO/USDC",
                "action": "buy",
                "amount": 10.0,
                "token": "USDC",
                "price": 2.0,
                "token_amount": 5.0,
                "timestamp": 1_700_000_000,
            },
        )
        self.assertEqual(response.status_code, 403)
        self.assertIn("demo", response.json()["detail"].lower())

    def test_trade_history_reads_demo_fills(self):
        self.portfolio.apply_fill(self._proposal())
        response = self.client.get("/portfolio/trades")
        self.assertEqual(response.status_code, 200)
        trades = response.json()
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0]["network"], "demo")
        self.assertEqual(trades[0]["pair"], "AERO/USDC")
        self.assertAlmostEqual(trades[0]["amount"], 200.0)
        self.assertAlmostEqual(trades[0]["token_amount"], 100.0)

    def test_reset_clears_the_demo_portfolio(self):
        self.portfolio.apply_fill(self._proposal())
        response = self.client.post("/portfolio/demo/reset")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["cash"], 1000.0)
        self.assertEqual(self.controller.user_holdings, {"USDC": 1000.0})

    def test_completing_a_proposal_fills_the_virtual_portfolio(self):
        from unittest.mock import patch

        self.controller.proposals = [self._proposal()]
        with patch.object(self.controller, "_persist_state"), patch.object(
            self.controller.audit_agent, "log"
        ):
            self.controller.update_proposal_status("demo-1", "executed")
        self.assertEqual(self.controller.proposals[0].status, "executed")
        self.assertAlmostEqual(self.portfolio.cash, 800.0)
        self.assertAlmostEqual(self.portfolio.positions["AERO"]["qty"], 100.0)
        self.assertEqual(len(self.portfolio.fills), 1)

    def test_repeated_completion_does_not_double_fill(self):
        from unittest.mock import patch

        self.controller.proposals = [self._proposal()]
        with patch.object(self.controller, "_persist_state"), patch.object(
            self.controller.audit_agent, "log"
        ):
            self.controller.update_proposal_status("demo-1", "executed")
            self.controller.update_proposal_status("demo-1", "executed")
        self.assertEqual(len(self.portfolio.fills), 1)
        self.assertAlmostEqual(self.portfolio.cash, 800.0)


if __name__ == "__main__":
    unittest.main()

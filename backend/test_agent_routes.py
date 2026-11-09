import unittest
from unittest.mock import Mock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import routes_agents
from app.models.agents import AgentStatus


class AgentRouteTests(unittest.TestCase):
    def setUp(self):
        self.fake = Mock()
        self.fake.get_status.return_value = AgentStatus(running=False)
        self.patcher = patch.object(routes_agents, "controller", self.fake)
        self.patcher.start()
        app = FastAPI()
        app.include_router(routes_agents.router, prefix="/agents")
        self.client = TestClient(app)

    def tearDown(self):
        self.patcher.stop()

    def test_complete_accepts_tx_hash_in_json_body(self):
        response = self.client.post(
            "/agents/proposals/p1/complete", json={"tx_hash": "0xabc"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["tx_hash"], "0xabc")
        self.fake.update_proposal_status.assert_called_once_with(
            "p1", "executed", "0xabc"
        )

    def test_complete_still_accepts_legacy_query_parameter(self):
        response = self.client.post("/agents/proposals/p2/complete?tx_hash=0xdef")
        self.assertEqual(response.status_code, 200)
        self.fake.update_proposal_status.assert_called_once_with(
            "p2", "executed", "0xdef"
        )

    def test_halt_and_resume(self):
        response = self.client.post("/agents/halt", json={"reason": "test"})
        self.assertEqual(response.status_code, 200)
        self.fake.halt.assert_called_once_with("test")
        self.client.post("/agents/resume")
        self.fake.resume.assert_called_once()

    def test_holdings_are_ignored_in_demo_mode(self):
        self.fake.demo = True
        self.fake.demo_portfolio.holdings.return_value = {"USDC": 1000.0}
        response = self.client.post("/agents/holdings", json={"ETH": 5.0})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ignored", "holdings": {"USDC": 1000.0}})


if __name__ == "__main__":
    unittest.main()

from ..models.agents import AnalysisRecommendation, RiskAssessment

class RiskAgent:
    def __init__(self):
        self.name = "RiskAgent"
        self.max_slippage = 0.5 # 0.5%
        self.max_gas_gwei = 50.0
        self.min_profit_usd = 0.10
        self.max_position_size_usd = 100.0 # Example limit

    def validate(self, recommendation: AnalysisRecommendation, user_holdings: dict = {}, current_gas_gwei: float = 20.0) -> RiskAssessment:
        """
        Validate a trading recommendation against risk parameters.
        """
        
        # 1. Holdings Check for SELL
        if recommendation.action == "sell":
            token = recommendation.token
            balance = user_holdings.get(token, 0.0)
            if balance <= 0:
                 return RiskAssessment(
                    approved=False,
                    reason=f"Cannot SELL {token}: No holdings found."
                )

        # 2. Gas Check
        if current_gas_gwei > self.max_gas_gwei:
            return RiskAssessment(
                approved=False,
                reason=f"Gas price {current_gas_gwei} Gwei exceeds limit {self.max_gas_gwei} Gwei"
            )

        # 2. Confidence Check
        if recommendation.confidence < 0.5:
            return RiskAssessment(
                approved=False,
                reason=f"Confidence {recommendation.confidence} below threshold 0.5"
            )

        # 3. Profit/Loss Logic (simplified)
        # In a real scenario, we would check estimated PnL vs Gas Cost
        
        estimated_gas_cost_usd = current_gas_gwei * 21000 * 1e-9 * 3000 # Rough estimate: 21k gas * price * ETH price
        # ... logic to check if profit > gas ...

        # 4. Slippage (Passed as param to be enforced by Execution)
        
        return RiskAssessment(
            approved=True,
            reason="Risk checks passed",
            max_slippage=self.max_slippage,
            estimated_gas=current_gas_gwei
        )

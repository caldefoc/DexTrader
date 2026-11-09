import uuid
import time
from ..models.agents import AnalysisRecommendation, RiskAssessment, TradeProposal

class ExecutionAgent:
    def __init__(self):
        self.name = "ExecutionAgent"

    def record_execution(self, proposal: TradeProposal, tx_hash: str):
        """
        Record a successful execution to trades.json using portfolio service.
        
        Trade record semantics:
        - amount: the QUOTE currency amount (USDC spent for buys, USDC received for sells)
        - token_amount: the BASE token quantity (tokens bought or tokens sold)
        - token: the quote currency symbol (typically "USDC")
        - price: unit price of the token in USDC
        """
        import time
        from ..models.portfolio import TradeExecution
        from ..services.portfolio import add_trade
        
        # proposal.amount is always in TOKEN units:
        #   buy  -> amount = tokens to receive  (usd_amount / price)
        #   sell -> amount = tokens to sell      (holding * sell_pct)
        token_qty = proposal.amount
        usd_amount = proposal.amount * proposal.price if proposal.price else 0.0
        
        trade = TradeExecution(
            tx_hash=tx_hash,
            network="base", 
            pair=f"{proposal.token}/USDC",
            action=proposal.action,
            amount=usd_amount,          # USDC (spent for buys, received for sells)
            token="USDC",               # Currency that was spent/received
            price=proposal.price,       # Unit price in USDC
            token_amount=token_qty,     # Token quantity (bought or sold)
            status="completed",
            timestamp=int(time.time())
        )
        
        try:
            add_trade(trade)
            print(f"[ExecutionAgent] Recorded trade: {tx_hash}")
        except Exception as e:
            print(f"[ExecutionAgent] Failed to record trade: {e}")

    def create_proposal(self, recommendation: AnalysisRecommendation, risk_assessment: RiskAssessment, user_holdings: dict = {}, market_prices: dict = {}) -> TradeProposal:
        """
        Create a formal trade proposal for human approval.
        """
        
        # Calculate Buying Power (ETH + USDC)
        # Use real prices if available, otherwise fallback to defaults
        eth_price = market_prices.get("ETH", 2500.0)
        usdc_price = market_prices.get("USDC", 1.0)
        
        # Normalize holdings keys to uppercase for safety
        normalized_holdings = {k.upper(): v for k, v in user_holdings.items()}
        
        # Log available holdings for debugging buying power issues
        print(f"[ExecutionAgent] calculating buying power. Holdings: {normalized_holdings}")

        # Mock holdings if empty (for demo/testing purposes when wallet is not connected to backend)
        # This ensures the user sees a valid proposal instead of zero amounts.
        using_fallback_power = False
        if not user_holdings:
            user_holdings = {"ETH": 1.0, "USDC": 1000.0}
            normalized_holdings = user_holdings
            using_fallback_power = True
        
        eth_amt = normalized_holdings.get("ETH", 0.0)
        usdc_amt = normalized_holdings.get("USDC", 0.0)
        weth_amt = normalized_holdings.get("WETH", 0.0) # Include WETH in buying power
        
        buying_power = ((eth_amt + weth_amt) * eth_price) + (usdc_amt * usdc_price)
        
        # 8% Rule
        max_trade_val = buying_power * 0.08
        target_position_size = max_trade_val # "buy 25% SHIB ... = 25% of 8% of total buying power" -> target pos is the 8% chunk?
        # User said: "buy 25% SHIB at -2% price = 25% of 8% of the total buying power amount"
        # So Target Position Size = 8% of Buying Power.
        
        amount = 0.0
        
        if recommendation.action == "buy":
            # Buy Logic
            # - At -2% (Step 1): 20-25% of target position
            # - At -4% (Step 2): 30-35% of target position
            # - At -6% (Step 3): 40-50% of target position
            
            # Check for insufficient funds
            # Relaxed rule: Allow trading if buying power > $5.0 (covers user's $14.54 case)
            if buying_power < 5.0 and not using_fallback_power: 
                return TradeProposal(
                    id=str(uuid.uuid4()),
                    token=recommendation.token,
                    action=recommendation.action,
                    amount=0.0,
                    price=recommendation.price,
                    pct_change=recommendation.pct_change,
                    reason=f"{recommendation.reason} (Insufficient Buying Power: ${buying_power:.2f} - Holdings: {normalized_holdings})",
                    slippage=risk_assessment.max_slippage,
                    gas_limit=250000, 
                    status="rejected", # Auto-reject if no funds
                    timestamp=time.time()
                )

            # Extract step from reason string? Or calculate again?
            # AnalysisAgent put reason: "Price ... (Buy Step X)"
            step = 1
            if "Step 2" in recommendation.reason: step = 2
            elif "Step 3" in recommendation.reason: step = 3
            
            pct_of_target = 0.25
            if step == 2: pct_of_target = 0.35
            elif step == 3: pct_of_target = 0.50
            
            usd_amount_to_buy = target_position_size * pct_of_target

            # Auto-reject dust trades below $0.50 (not worth the gas)
            DUST_THRESHOLD_USD = 0.50
            if usd_amount_to_buy < DUST_THRESHOLD_USD:
                return TradeProposal(
                    id=str(uuid.uuid4()),
                    token=recommendation.token,
                    action=recommendation.action,
                    amount=0.0,
                    price=recommendation.price,
                    pct_change=recommendation.pct_change,
                    reason=f"{recommendation.reason} (Trade too small: ${usd_amount_to_buy:.2f} < ${DUST_THRESHOLD_USD} dust threshold)",
                    slippage=risk_assessment.max_slippage,
                    gas_limit=250000, 
                    status="rejected",
                    timestamp=time.time()
                )

            # Minimum Trade Size Logic
            # Ensure trade is at least $2.00 to make sense (gas/dust)
            # If calculated amount < $2.00, boost it to $2.00 (capped by buying power)
            MIN_TRADE_USD = 2.0
            
            if usd_amount_to_buy < MIN_TRADE_USD:
                # Boost to min trade size
                usd_amount_to_buy = MIN_TRADE_USD
                
                # Check if this exceeds safe allocation for small portfolios
                # For small portfolios (<$100), allow up to 30% per trade to meet minimums
                if buying_power < 100.0:
                    if usd_amount_to_buy > (buying_power * 0.30):
                         usd_amount_to_buy = buying_power * 0.30
                else:
                    # For larger portfolios, stick to max 10% per trade override
                    if usd_amount_to_buy > (buying_power * 0.10):
                        usd_amount_to_buy = buying_power * 0.10
                        
            # Absolute hard cap: cannot exceed available buying power (minus gas buffer)
            if usd_amount_to_buy > (buying_power * 0.95):
                usd_amount_to_buy = buying_power * 0.95

            if recommendation.price > 0:
                amount = usd_amount_to_buy / recommendation.price
            
        elif recommendation.action == "sell":
            # Sell Logic
            # - At +2% : 25% of holdings
            # - At +4% : 25% of holdings
            # - At +5% : 25% of holdings
            # - At +10%: 20% of holdings (leave 5%)
            
            current_holding = user_holdings.get(recommendation.token, 0.0)
            
            # Fallback for simulation if holding is zero
            if current_holding == 0 and recommendation.price > 0:
                current_holding = 1000.0 / recommendation.price

            sell_pct = 0.25 # Default
            
            # Extract percentage from reason - handle both avg_entry and fallback cases
            try:
                import re
                # Handle avg_entry case: "Profit X.X% (Target Hit)..." or "Price X.X% above Entry" (legacy)
                match = re.search(r"Profit (\d+\.?\d*)%", recommendation.reason)
                if not match:
                    match = re.search(r"Price (\d+\.?\d*)% above Entry", recommendation.reason)
                
                if match:
                    pct_gain = float(match.group(1))
                    if pct_gain >= 10.0: sell_pct = 0.20
                    elif pct_gain >= 5.0: sell_pct = 0.25
                    elif pct_gain >= 4.0: sell_pct = 0.25
                    elif pct_gain >= 2.0: sell_pct = 0.25
                else:
                    # Handle fallback case: "Pump > X.X% (Speculative Sell)" or similar
                    match = re.search(r"Pump > (\d+\.?\d*)%", recommendation.reason)
                    if match:
                        pct_gain = float(match.group(1))
                        if pct_gain >= 15.0: sell_pct = 0.50  # Sell more on big pumps
                        elif pct_gain >= 10.0: sell_pct = 0.35
                        elif pct_gain >= 5.0: sell_pct = 0.25
                        elif pct_gain >= 2.0: sell_pct = 0.25  # Sell 25% for 2-5% pumps
            except:
                pass
                
            amount = current_holding * sell_pct
            
            # Calculate USD value of sell
            usd_amount_to_sell = amount * recommendation.price if recommendation.price > 0 else 0.0
            
            # Auto-reject dust trades below $0.50 (not worth the gas)
            DUST_THRESHOLD_USD = 0.50
            if usd_amount_to_sell < DUST_THRESHOLD_USD:
                return TradeProposal(
                    id=str(uuid.uuid4()),
                    token=recommendation.token,
                    action=recommendation.action,
                    amount=0.0,
                    price=recommendation.price,
                    pct_change=recommendation.pct_change,
                    reason=f"{recommendation.reason} (Trade too small: ${usd_amount_to_sell:.2f} < ${DUST_THRESHOLD_USD} dust threshold)",
                    slippage=risk_assessment.max_slippage,
                    gas_limit=250000, 
                    status="rejected",
                    timestamp=time.time()
                )
        
        # Fallback / Sanity Check
        if amount <= 0:
            amount = 0.0
            
        proposal = TradeProposal(
            id=str(uuid.uuid4()),
            token=recommendation.token,
            action=recommendation.action,
            amount=amount,
            price=recommendation.price,
            pct_change=recommendation.pct_change,
            reason=recommendation.reason,
            slippage=risk_assessment.max_slippage,
            gas_limit=250000, 
            status="pending",
            timestamp=time.time()
        )
        
        return proposal

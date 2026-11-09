from typing import List
from ..models.agents import AnalysisRecommendation
from ..models.market import MarketSnapshot

class AnalysisAgent:
    def __init__(self):
        self.name = "AnalysisAgent"

    def analyze(self, snapshot: MarketSnapshot, position_states: dict = {}, user_holdings: dict = {}) -> List[AnalysisRecommendation]:
        """
        Analyze market snapshot and produce recommendations based on:
        - Price vs VWAP (Buying)
        - Price vs Avg Entry (Selling)
        """
        recommendations = []
        print(f"[AnalysisAgent] Analyzing {len(snapshot.pairs)} pairs. Holdings: {user_holdings}")
        
        for pair in snapshot.pairs:
            token = pair.base_symbol
            price = pair.price
            
            # Use real VWAP if available, otherwise default to price (neutral)
            # Avoid forcing artificial buy signals with mock data
            vwap = price 
            
            state = position_states.get(token, {"avg_entry": 0.0, "buy_step": 0})
            avg_entry = state["avg_entry"]
            current_buy_step = state["buy_step"]
            
            # Check actual holdings to ensure we know if we hold it
            has_holding = user_holdings.get(token, 0) > 0 or user_holdings.get(token.upper(), 0) > 0
            
            action = "hold"
            confidence = 0.0
            reason = "Market is neutral"
            
            # --- BUY LOGIC ---
            # Only buy on dips (negative change)
            
            if pair.change_24h <= -2.0:
                 # Minor Dip - allow buying up to step 3 (gradual accumulation)
                 if current_buy_step <= 3:
                     action = "buy"
                     confidence = 0.6
                     reason = f"Price down {abs(pair.change_24h):.1f}% (Dip Buy Step {current_buy_step + 1})"
                 else:
                     print(f"[AnalysisAgent] {token}: Dip {pair.change_24h:.1f}% but buy_step={current_buy_step} (max 3 reached)")
            else:
                 if pair.change_24h < 0:
                     print(f"[AnalysisAgent] {token}: Dip only {pair.change_24h:.1f}% (needs <= -2.0 for buy)")
            
            if pair.change_24h <= -5.0:
                 # Major Dip - allow buying up to step 4 for larger dips
                 if current_buy_step <= 4:
                     action = "buy"
                     confidence = 0.7
                     reason = f"Price down {abs(pair.change_24h):.1f}% (Value Buy Step {current_buy_step + 1})"
                 else:
                     print(f"[AnalysisAgent] {token}: Major dip {pair.change_24h:.1f}% but buy_step={current_buy_step} > 4")

            # --- SELL LOGIC ---
            if has_holding:
                # 1. Check against Entry Price if known
                if avg_entry > 0:
                    pct_gain = (price - avg_entry) / avg_entry
                    
                    # Dynamic Profit Target:
                    # If token is down today (red), be slightly more conservative about selling.
                    # But keep the threshold reasonable so moderate gains still trigger.
                    target_gain = 0.02 # Default 2%
                    if pair.change_24h < 0:
                        target_gain = 0.03 # Require 3% profit if token is down today (was 5%, too restrictive)
                        
                    if pct_gain >= target_gain:
                        action = "sell"
                        confidence = 0.8
                        reason = f"Profit {pct_gain*100:.1f}% (Target Hit) [Entry: {avg_entry:.6f}, Curr: {price:.6f}]"
                
                # 2. Fallback: Speculative Sell on Pumps (if entry unknown or just huge pump)
                if action != "sell" and pair.change_24h >= 3.0:
                     action = "sell"
                     confidence = 0.7
                     reason = f"Pump > {pair.change_24h:.1f}% (Speculative Take Profit)"
                     
                # 3. Smaller pump sell if we have no entry data
                if action != "sell" and avg_entry == 0 and pair.change_24h >= 2.0:
                     action = "sell"
                     confidence = 0.6
                     reason = f"Up {pair.change_24h:.1f}% (Blind Take Profit)"

            # Sanity Check: Don't buy if it's pumping
            # Ensure we don't buy if change is positive, regardless of what other logic says
            if action == "buy" and pair.change_24h > 0:
                action = "hold"
                reason = f"Price is up ({pair.change_24h:.1f}%), waiting for pullback"
                
            # Double Sanity Check for "Spam Buys":
            # If the reason implies a dip but price is actually up, something is wrong.
            if action == "buy" and "Dip" in reason and pair.change_24h > -0.5:
                 action = "hold"
                 reason = f"Dip too small ({pair.change_24h:.1f}%), holding"

            rec = AnalysisRecommendation(
                token=token,
                action=action,
                confidence=confidence,
                reason=reason,
                price=price,
                pct_change=pair.change_24h,
                rsi=50.0,
                vwap=vwap,
                volume_spike=False
            )
            
            if action != "hold":
                recommendations.append(rec)
                
        return recommendations

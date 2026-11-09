from typing import List

from fastapi import APIRouter, Query
from langchain_openai import ChatOpenAI

from ..models.market import MarketSnapshot
from ..models.signals import Signal
from ..api.routes_market import get_cached_market_data
from ..services.strategy import evaluate_market
from ..core.config import OPENAI_API_KEY, DEEPSEEK_API_KEY
from ..agents.langchain_signals import generate_signals_with_langchain, generate_signals_with_deepseek


router = APIRouter()


@router.get("/", response_model=List[Signal])
async def get_signals(limit: int = Query(50, ge=1, le=500)) -> List[Signal]:
    pairs = await get_cached_market_data()
    # Apply limit to the cached data
    pairs = pairs[:limit]
    snapshot = MarketSnapshot(pairs=pairs)
    
    # Try DeepSeek first if available
    if DEEPSEEK_API_KEY:
        try:
            return await generate_signals_with_deepseek(DEEPSEEK_API_KEY, snapshot)
        except Exception as e:
            err_str = str(e)
            print(f"DeepSeek error: {e}")
            # Skip OpenAI fallback on billing/quota errors — they won't recover
            if "402" in err_str or "429" in err_str or "quota" in err_str.lower() or "payment" in err_str.lower():
                print("DeepSeek billing error, skipping OpenAI fallback, using rules")
                return evaluate_market(snapshot)
    
    # Fall back to OpenAI if DeepSeek fails or isn't configured
    if OPENAI_API_KEY:
        try:
            llm = ChatOpenAI(
                api_key=OPENAI_API_KEY, 
                model="gpt-4o-mini", 
                temperature=0
            )
            return await generate_signals_with_langchain(llm, snapshot)
        except Exception as e:
            print(f"OpenAI error, falling back to rules: {e}")
            return evaluate_market(snapshot)
    
    return evaluate_market(snapshot)


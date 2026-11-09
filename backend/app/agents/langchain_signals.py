import time
import json
from typing import List

import httpx
from langchain_openai import ChatOpenAI
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import PydanticOutputParser
from pydantic import BaseModel, Field

from ..models.market import MarketSnapshot
from ..models.signals import Signal


class SignalList(BaseModel):
    signals: List[Signal] = Field(description="List of trading signals")


def build_signal_chain(llm):
    parser = PydanticOutputParser(pydantic_object=SignalList)

    template = """You are an expert crypto trading assistant.
Analyze the following market data and produce buy, sell, or hold signals.
For each signal, provide a confidence score (0.0 to 1.0) and a brief explanation (reasoning).

Market Data:
{market_json}

{format_instructions}
"""
    prompt = PromptTemplate(
        template=template,
        input_variables=["market_json"],
        partial_variables={"format_instructions": parser.get_format_instructions()},
    )

    return prompt | llm | parser


async def generate_signals_with_langchain(
    llm: ChatOpenAI, snapshot: MarketSnapshot
) -> List[Signal]:
    chain = build_signal_chain(llm)
    mini_snapshot = snapshot.model_copy()
    mini_snapshot.pairs = mini_snapshot.pairs[:10]

    market_json = mini_snapshot.model_dump_json()

    try:
        result = await chain.ainvoke({"market_json": market_json})
        signals: List[Signal] = result.signals
        for s in signals:
            s.source = "llm"
            s.created_at = time.time()
        return signals
    except Exception as e:
        print(f"Error generating signals: {e}")
        raise


async def generate_signals_with_deepseek(
    api_key: str, snapshot: MarketSnapshot
) -> List[Signal]:
    """Generate signals using DeepSeek API directly."""
    mini_snapshot = snapshot.model_copy()
    mini_snapshot.pairs = mini_snapshot.pairs[:10]
    market_json = mini_snapshot.model_dump_json()
    
    # Build the prompt for DeepSeek
    system_prompt = """You are an expert crypto trading assistant.
Analyze the following market data and produce buy, sell, or hold signals.
For each signal, provide a confidence score (0.0 to 1.0) and a brief explanation (reasoning).

Respond in JSON format with this structure:
{
  "signals": [
    {
      "pair": "BTC",
      "action": "buy",
      "confidence": 0.85,
      "reasoning": "Strong upward momentum with volume increase"
    }
  ]
}"""
    
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            "https://api.deepseek.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            },
            json={
                "model": "deepseek-chat",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Market Data:\n{market_json}"}
                ],
                "temperature": 0,
                "response_format": {"type": "json_object"}
            }
        )
        response.raise_for_status()
        data = response.json()
        
        # Parse the response
        content = data["choices"][0]["message"]["content"]
        result = json.loads(content)
        
        signals: List[Signal] = []
        for sig_data in result.get("signals", []):
            signal = Signal(
                pair=sig_data.get("pair", sig_data.get("symbol", "UNKNOWN")),
                action=sig_data["action"],
                confidence=sig_data["confidence"],
                explanation=sig_data.get("reasoning", sig_data.get("explanation", "")),
                source="deepseek",
                created_at=time.time()
            )
            signals.append(signal)
        
        return signals

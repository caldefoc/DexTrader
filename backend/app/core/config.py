import os

from dotenv import load_dotenv, find_dotenv


load_dotenv(find_dotenv())


COINMARKETCAP_API_KEY = os.getenv("COINMARKETCAP_API_KEY")
COINGECKO_API_KEY = os.getenv("COINGECKO_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")

# Public demo: simulated portfolio, real market data, no wallet.
DEMO_MODE = os.getenv("DEMO_MODE", "0").strip().lower() in ("1", "true", "yes", "on")


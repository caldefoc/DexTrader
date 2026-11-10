---
kind: external_dependency
name: DeepSeek chat model (first-tier signal source)
slug: deepseek
category: external_dependency
category_hints:
    - sdk_real_api
scope:
    - '**'
source_files:
    - backend/app/agents/langchain_signals.py
---

### Role
First-tier LLM for generating trade signals via a direct HTTP call to `api.deepseek.com` using model `deepseek-chat` with `temperature: 0` and JSON output. Falls back to OpenAI `gpt-4o-mini` through LangChain if unavailable.

### Stable integration notes
- `DEEPSEEK_API_KEY` is read from `.env` and sent with the request.
- Verify exact request shape and auth header against DeepSeek's API docs.
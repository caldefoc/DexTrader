---
kind: external_dependency
name: OpenAI GPT-4o-mini (fallback signal source)
slug: openai
category: external_dependency
category_hints:
    - sdk_real_api
scope:
    - '**'
source_files:
    - backend/app/agents/langchain_signals.py
---

### Role
Second-tier LLM invoked through LangChain + `langchain-openai` when the DeepSeek call fails. Model is `gpt-4o-mini`.

### Stable integration notes
- `OPENAI_API_KEY` is read from `.env`.
- Verify LangChain/OpenAI client configuration against their docs.
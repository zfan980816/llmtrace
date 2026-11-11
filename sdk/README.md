# llmtrace-sdk

One-line LLM observability for LLMTrace - a self-hosted LangSmith alternative.

```bash
pip install llmtrace-sdk
```

## Quick start

```python
from llmtrace import wrap_openai

client = wrap_openai(openai.OpenAI())   # done. every call is traced
```

Also ships with:
- `wrap_anthropic` - Anthropic client (streaming supported)
- `@trace` / `@span` decorators - sync & async plain functions
- `record_llm_call` - manual LLM call recording
- batch upload + disk buffer - retries after network failures
- PII masking - phone / email / ID numbers

See the server docs for setup.

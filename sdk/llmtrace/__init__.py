from .client import configure, record_llm_call, span, trace

__all__ = [
    "configure",
    "record_llm_call",
    "span",
    "trace",
    "wrap_openai",
    "wrap_anthropic",
]
__version__ = "0.1.0"


def wrap_openai(client):
    """Auto-instrument an OpenAI SDK v1 client (chat.completions.create)."""
    from .integrations.openai import wrap_openai as _wrap
    return _wrap(client)


def wrap_anthropic(client):
    """Auto-instrument an Anthropic SDK client (messages.create, non-streaming)."""
    from .integrations.anthropic import wrap_anthropic as _wrap
    return _wrap(client)

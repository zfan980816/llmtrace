"""Auto-instrumentation for the Anthropic python SDK (non-streaming).

Usage:
    import anthropic
    import llmtrace

    client = llmtrace.wrap_anthropic(anthropic.Anthropic())
    msg = client.messages.create(model="claude-3-5-haiku", messages=[...])
"""

from ..client import span


def wrap_anthropic(client):
    """Patch client.messages.create so every call is traced."""
    original = client.messages.create

    def traced_create(*args, **kwargs):
        if kwargs.get("stream"):
            # Streaming (message stream manager) is not instrumented yet.
            return original(*args, **kwargs)
        model = kwargs.get("model")
        messages = kwargs.get("messages")
        with span(model or "anthropic-messages", span_type="llm", input=messages, model=model) as rec:
            response = original(*args, **kwargs)
            texts = [
                block.text
                for block in getattr(response, "content", [])
                if hasattr(block, "text")
            ]
            rec["output"] = "".join(texts) or None
            usage = getattr(response, "usage", None)
            if usage is not None:
                rec["prompt_tokens"] = getattr(usage, "input_tokens", 0) or 0
                rec["completion_tokens"] = getattr(usage, "output_tokens", 0) or 0
                rec["total_tokens"] = rec["prompt_tokens"] + rec["completion_tokens"]
            return response

    client.messages.create = traced_create
    return client

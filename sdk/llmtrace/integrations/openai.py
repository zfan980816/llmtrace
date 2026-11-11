"""Auto-instrumentation for the OpenAI python SDK (v1.x client).

Usage:
    from openai import OpenAI
    import llmtrace

    client = llmtrace.wrap_openai(OpenAI())
    resp = client.chat.completions.create(model="gpt-4o-mini", messages=[...])
    # -> an llm span with model / input / output / token usage / latency is recorded
"""

from ..client import span


def _record_response(rec, response):
    choices = getattr(response, "choices", None)
    if choices:
        msg = getattr(choices[0], "message", None)
        rec["output"] = getattr(msg, "content", None) or getattr(choices[0], "text", None)
    usage = getattr(response, "usage", None)
    if usage is not None:
        rec["prompt_tokens"] = getattr(usage, "prompt_tokens", 0) or 0
        rec["completion_tokens"] = getattr(usage, "completion_tokens", 0) or 0
        rec["total_tokens"] = rec["prompt_tokens"] + rec["completion_tokens"]


def wrap_openai(client):
    """Patch client.chat.completions.create so every call is traced."""
    original = client.chat.completions.create

    def traced_create(*args, **kwargs):
        model = kwargs.get("model")
        messages = kwargs.get("messages")
        if kwargs.get("stream"):
            return _traced_stream(original, args, kwargs, model, messages)
        with span(model or "openai-chat", span_type="llm", input=messages, model=model) as rec:
            response = original(*args, **kwargs)
            _record_response(rec, response)
            return response

    client.chat.completions.create = traced_create
    return client


def _traced_stream(original, args, kwargs, model, messages):
    """Generator wrapper: keeps the span open for the whole stream iteration."""
    with span(model or "openai-chat", span_type="llm", input=messages, model=model) as rec:
        pieces = []
        for chunk in original(*args, **kwargs):
            try:
                delta = chunk.choices[0].delta
                text = getattr(delta, "content", None)
            except (AttributeError, IndexError, TypeError):
                text = None
            if text:
                pieces.append(text)
            usage = getattr(chunk, "usage", None)
            if usage is not None:
                rec["prompt_tokens"] = getattr(usage, "prompt_tokens", 0) or 0
                rec["completion_tokens"] = getattr(usage, "completion_tokens", 0) or 0
                rec["total_tokens"] = rec["prompt_tokens"] + rec["completion_tokens"]
            yield chunk
        rec["output"] = "".join(pieces) or None

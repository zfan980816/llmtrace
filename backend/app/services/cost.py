"""Rough token pricing (USD per 1M tokens: input, output). Update as needed."""

PRICING = {
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4.1": (2.00, 8.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "o3-mini": (1.10, 4.40),
    "claude-3-5-sonnet": (3.00, 15.00),
    "claude-3-5-haiku": (0.80, 4.00),
    "claude-sonnet-4": (3.00, 15.00),
    "claude-haiku-4": (0.80, 4.00),
    "deepseek-chat": (0.27, 1.10),
    "deepseek-reasoner": (0.55, 2.19),
    "qwen-plus": (0.40, 1.20),
    "qwen-turbo": (0.05, 0.20),
}


def estimate_cost(model, prompt_tokens, completion_tokens):
    """Estimate cost in USD. Unknown models return 0."""
    if not model:
        return 0.0
    m = model.lower()
    key = next((k for k in sorted(PRICING, key=len, reverse=True) if k in m), None)
    if key is None:
        return 0.0
    price_in, price_out = PRICING[key]
    return (prompt_tokens or 0) / 1e6 * price_in + (completion_tokens or 0) / 1e6 * price_out


"""PII masking applied server-side (defense in depth) and mirrored in the SDK."""
import re

PATTERNS = {
    "phone": (re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"), "[phone]"),
    "email": (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "[email]"),
    "id_card": (re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)"), "[id]"),
}


def mask_text(text: str) -> str:
    for pattern, replacement in PATTERNS.values():
        text = pattern.sub(replacement, text)
    return text


def mask_pii(obj):
    """Recursively mask phone numbers / emails / ID numbers inside strings."""
    if isinstance(obj, str):
        return mask_text(obj)
    if isinstance(obj, dict):
        return {k: mask_pii(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [mask_pii(v) for v in obj]
    return obj

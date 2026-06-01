import json as _json
import re as _re

_FENCE = _re.compile(r"^```(?:json)?\s*|\s*```$", _re.IGNORECASE)


def parse_items(raw: str) -> list[dict]:
    """Parse model output into a list of {'type': str, 'text': str}.

    Tolerant of code fences and surrounding prose; malformed output yields []."""
    if not raw or not raw.strip():
        return []
    cleaned = _FENCE.sub("", raw.strip())
    # fall back to the first [...] block if the model added prose
    if not cleaned.lstrip().startswith("["):
        m = _re.search(r"\[.*\]", cleaned, _re.DOTALL)
        cleaned = m.group(0) if m else cleaned
    try:
        data = _json.loads(cleaned)
    except ValueError:
        return []
    if not isinstance(data, list):
        return []
    out = []
    for it in data:
        if (isinstance(it, dict) and isinstance(it.get("type"), str)
                and isinstance(it.get("text"), str)):
            out.append({"type": it["type"], "text": it["text"]})
    return out


from thickanon.core.types import Entity
from thickanon.detectors.normalize import normalize_type


def resolve_spans(text: str, items: list[dict], confidence: float, base: int = 0) -> list[Entity]:
    """Locate each item's verbatim 'text' in `text` and emit Entity spans.

    Items whose text does not occur verbatim are dropped (hallucinations).
    Every occurrence of a found substring becomes its own span. Offsets are
    shifted by `base` (used when `text` is a chunk of a larger fragment)."""
    out = []
    for it in items:
        needle = it["text"]
        if not needle:
            continue
        etype = normalize_type(it["type"])
        start = text.find(needle)
        while start != -1:
            out.append(Entity(base + start, base + start + len(needle), etype,
                              confidence, needle))
            start = text.find(needle, start + len(needle))
    return out


def build_prompt(text: str, categories: list[str], custom_instruction: str = "") -> str:
    cats = ", ".join(categories)
    extra = f"\nAdditional guidance: {custom_instruction}" if custom_instruction.strip() else ""
    return (
        "You extract sensitive data spans from text.\n"
        f"Categories to find: {cats}.{extra}\n"
        "Return ONLY a JSON array of objects with keys \"type\" (one of the "
        "categories) and \"text\" (the exact substring, copied verbatim from the "
        "input). Do not include offsets. If nothing is found, return [].\n"
        "----- INPUT -----\n"
        f"{text}\n"
        "----- END INPUT -----"
    )

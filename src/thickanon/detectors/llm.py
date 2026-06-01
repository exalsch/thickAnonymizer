import json as _json
import re as _re
from typing import Callable

from thickanon.core.types import Entity
from thickanon.detectors.normalize import normalize_type


def _balanced_array(s: str, start: int) -> str | None:
    """Return the balanced [...] substring beginning at index `start`, or None.
    String-aware so brackets inside JSON strings don't affect depth."""
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(s)):
        c = s[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        else:
            if c == '"':
                in_str = True
            elif c == "[":
                depth += 1
            elif c == "]":
                depth -= 1
                if depth == 0:
                    return s[start:i + 1]
    return None


def parse_items(raw: str) -> list[dict]:
    """Parse model output into a list of {'type': str, 'text': str}.

    Tolerant of code fences and surrounding prose; malformed output yields []."""
    if not raw or not raw.strip():
        return []
    s = raw.strip()
    for i, ch in enumerate(s):
        if ch != "[":
            continue
        arr = _balanced_array(s, i)
        if arr is None:
            continue
        try:
            data = _json.loads(arr)
        except ValueError:
            continue
        if isinstance(data, list):
            out = []
            for it in data:
                if (isinstance(it, dict) and isinstance(it.get("type"), str)
                        and isinstance(it.get("text"), str)):
                    out.append({"type": it["type"], "text": it["text"]})
            return out
    return []


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


def iter_chunks(text: str, max_chars: int, overlap: int = 200) -> list[tuple[int, str]]:
    """Split text into overlapping windows of at most max_chars.

    Returns (base_offset, chunk_text) pairs covering the whole string. Overlap
    reduces the chance of splitting an entity across a boundary."""
    if not text:
        return []
    if len(text) <= max_chars:
        return [(0, text)]
    overlap = max(0, min(overlap, max_chars // 2))
    step = max(1, max_chars - overlap)
    chunks = []
    pos = 0
    while pos < len(text):
        chunks.append((pos, text[pos:pos + max_chars]))
        if pos + max_chars >= len(text):
            break
        pos += step
    return chunks


def llm_detect(text: str, llm_config, runner: Callable[[str], str]) -> list[Entity]:
    """Run the model over (chunked) text and return resolved Entity spans.

    `runner` maps a prompt to raw model text; injected so tests need no model."""
    seen = set()
    out = []
    for base, chunk in iter_chunks(text, llm_config.max_chunk_chars):
        prompt = build_prompt(chunk, llm_config.categories, llm_config.custom_instruction)
        items = parse_items(runner(prompt))
        for e in resolve_spans(chunk, items, llm_config.confidence, base=base):
            key = (e.entity_type, e.start, e.end)
            if key not in seen:
                seen.add(key)
                out.append(e)
    return out

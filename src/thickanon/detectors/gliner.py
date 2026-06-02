from thickanon.core.types import Entity
from thickanon.detectors.normalize import normalize_type


def iter_chunks(text: str, max_chars: int, overlap: int = 200) -> list[tuple[int, str]]:
    """Split text into overlapping windows of at most max_chars; (base, chunk)."""
    if not text:
        return []
    if len(text) <= max_chars:
        return [(0, text)]
    overlap = max(0, min(overlap, max_chars // 2))
    step = max(1, max_chars - overlap)
    chunks, pos = [], 0
    while pos < len(text):
        chunks.append((pos, text[pos:pos + max_chars]))
        if pos + max_chars >= len(text):
            break
        pos += step
    return chunks


def gliner_detect(text: str, cfg, model) -> list[Entity]:
    """Run GLiNER over (chunked) text, returning Entity spans with native offsets
    and scores. `model.predict_entities(chunk, labels, threshold)` returns dicts
    with label/text/start/end/score. `model` is injected so tests need no real model."""
    seen, out = set(), []
    for base, chunk in iter_chunks(text, cfg.max_chunk_chars):
        for sp in model.predict_entities(chunk, cfg.labels, threshold=cfg.threshold):
            score = sp.get("score", 0.0)
            if not isinstance(score, (int, float)) or score < cfg.threshold:
                continue
            start, end = sp.get("start"), sp.get("end")
            if not isinstance(start, int) or not isinstance(end, int):
                continue
            if start < 0 or end > len(chunk) or start >= end:
                continue  # defensive: offsets must be valid within the chunk
            surface = chunk[start:end]
            etype = normalize_type(sp["label"])
            gstart, gend = base + start, base + end
            key = (etype, gstart, gend)
            if key in seen:
                continue
            seen.add(key)
            out.append(Entity(gstart, gend, etype, score, surface))
    return out

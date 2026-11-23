import re

from thickanon.core.types import Entity
from thickanon.detectors.normalize import normalize_type

# GLiNER's own word splitter (gliner.data_processing.tokenizer.WhitespaceTokenSplitter).
# Counting with the same pattern makes a window of N words exactly N model words.
_WORD = re.compile(r"\w+(?:[-_]\w+)*|\S")


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


def iter_word_windows(text: str, max_words: int, overlap_words: int):
    """Split text into overlapping windows of at most max_words model words.

    Returns (base, own_start, own_end, window) tuples. Windows overlap, so a
    span can be seen by two windows, and a window that ends inside a name sees
    only part of it. Each window therefore owns the start positions in
    [own_start, own_end): the owned ranges partition the text, and every owned
    range ends at least overlap_words // 2 words before its window ends, so an
    entity that starts there is not cut off by the window edge.
    """
    if not text:
        return []
    words = list(_WORD.finditer(text))
    max_words = max(1, max_words)
    if len(words) <= max_words:
        return [(0, 0, len(text), text)]
    overlap_words = max(0, min(overlap_words, max_words // 2))
    step = max_words - overlap_words
    half = overlap_words // 2
    firsts = []
    first = 0
    while True:
        firsts.append(first)
        if first + max_words >= len(words):
            break
        first += step
    windows = []
    for k, first in enumerate(firsts):
        last_window = k == len(firsts) - 1
        base = 0 if k == 0 else words[first].start()
        end = len(text) if last_window else words[first + max_words - 1].end()
        own_start = 0 if k == 0 else words[first + half].start()
        own_end = len(text) if last_window else words[firsts[k + 1] + half].start()
        windows.append((base, own_start, own_end, text[base:end]))
    return windows


def _model_max_words(model):
    max_len = getattr(getattr(model, "config", None), "max_len", None)
    return max_len if isinstance(max_len, int) and max_len > 0 else None


def gliner_detect(text: str, cfg, model, progress=None) -> list[Entity]:
    """Run GLiNER over word windows of text, returning Entity spans with native
    offsets and scores. `model.predict_entities(chunk, labels, threshold)` returns
    dicts with label/text/start/end/score. `model` is injected so tests need no
    real model. progress(done, total) is called after each window."""
    max_words = cfg.max_chunk_words
    model_limit = _model_max_words(model)
    if model_limit is not None:
        max_words = min(max_words, model_limit)
    windows = iter_word_windows(text, max_words, cfg.chunk_overlap_words)
    seen, out = set(), []
    for index, (base, own_start, own_end, chunk) in enumerate(windows, start=1):
        for sp in model.predict_entities(chunk, cfg.labels, threshold=cfg.threshold):
            score = sp.get("score", 0.0)
            if not isinstance(score, (int, float)) or score < cfg.threshold:
                continue
            start, end = sp.get("start"), sp.get("end")
            if not isinstance(start, int) or not isinstance(end, int):
                continue
            if start < 0 or end > len(chunk) or start >= end:
                continue  # defensive: offsets must be valid within the chunk
            gstart, gend = base + start, base + end
            if not own_start <= gstart < own_end:
                continue  # another window owns this start and sees the whole span
            surface = chunk[start:end]
            etype = normalize_type(sp["label"])
            key = (etype, gstart, gend)
            if key in seen:
                continue
            seen.add(key)
            out.append(Entity(gstart, gend, etype, score, surface))
        if progress is not None:
            progress(index, len(windows))
    return out

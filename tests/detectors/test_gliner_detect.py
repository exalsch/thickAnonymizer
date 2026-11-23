import re
from types import SimpleNamespace

from thickanon.core.types import GLiNERConfig
from thickanon.detectors.gliner import gliner_detect


class StubModel:
    """Returns canned spans; ignores chunk text."""
    def __init__(self, items): self.items = items
    def predict_entities(self, text, labels, threshold=0.5):
        return list(self.items)


class FindStub:
    """Finds a needle in each chunk and returns its real chunk-local offsets."""
    def __init__(self, needle, label="person", score=0.9):
        self.needle, self.label, self.score = needle, label, score
    def predict_entities(self, text, labels, threshold=0.5):
        i = text.find(self.needle)
        if i == -1: return []
        return [{"label": self.label, "text": self.needle,
                 "start": i, "end": i + len(self.needle), "score": self.score}]


def test_offsets_score_and_type_normalized():
    text = "Patient John Carter at Berlin"   # John Carter @8..19, Berlin @23..29
    model = StubModel([
        {"label": "person", "text": "John Carter", "start": 8, "end": 19, "score": 0.9},
        {"label": "phone number", "text": "Berlin", "start": 23, "end": 29, "score": 0.8},
    ])
    ents = gliner_detect(text, GLiNERConfig(threshold=0.5), model)
    by = {e.entity_type: e for e in ents}
    assert text[by["PERSON"].start:by["PERSON"].end] == "John Carter"
    assert by["PERSON"].score == 0.9
    # "phone number" -> PHONE_NUMBER -> normalized to PHONE (same alias the spaCy
    # path uses), so both detectors emit a consistent [PHONE_n] token.
    assert "PHONE" in by


def test_below_threshold_dropped():
    model = StubModel([{"label": "person", "text": "x", "start": 0, "end": 1, "score": 0.3}])
    assert gliner_detect("x", GLiNERConfig(threshold=0.5), model) == []


def test_dedupes_across_chunks():
    text = "John " * 50
    ents = gliner_detect(text, GLiNERConfig(max_chunk_words=8, chunk_overlap_words=2), FindStub("John"))
    spans = [(e.start, e.end) for e in ents]
    assert spans and len(spans) == len(set(spans))   # no duplicate global spans


def test_out_of_range_offsets_skipped():
    model = StubModel([{"label": "person", "text": "zz", "start": 99, "end": 101, "score": 0.9}])
    assert gliner_detect("short", GLiNERConfig(), model) == []


# GLiNER's own word splitter (gliner.data_processing.tokenizer.WhitespaceTokenSplitter).
_GLINER_WORD = re.compile(r"\w+(?:[-_]\w+)*|\S")


class TruncatingStub:
    """Behaves like real GLiNER: it reads only the first max_len words of its
    input and silently ignores the rest. It finds the needle when the whole
    needle is inside the part it read."""

    def __init__(self, needle, max_len=384, score=0.9):
        self.needle, self.score = needle, score
        self.config = SimpleNamespace(max_len=max_len)
        self.longest_input_words = 0

    def predict_entities(self, text, labels, threshold=0.5):
        words = list(_GLINER_WORD.finditer(text))
        self.longest_input_words = max(self.longest_input_words, len(words))
        visible = words[self.config.max_len - 1].end() if len(words) > self.config.max_len else len(text)
        i = text.find(self.needle)
        if i == -1 or i + len(self.needle) > visible:
            return []
        return [{"label": "person", "text": self.needle,
                 "start": i, "end": i + len(self.needle), "score": self.score}]


class CutAtEdgeStub:
    """Finds the whole needle at 0.8. When a window ends inside the needle, it
    also reports the cut-off part at a higher score, as a real model can."""

    def __init__(self, needle):
        self.needle = needle

    def predict_entities(self, text, labels, threshold=0.5):
        i = text.find(self.needle)
        if i != -1:
            return [{"label": "person", "text": self.needle,
                     "start": i, "end": i + len(self.needle), "score": 0.8}]
        tail = text.rstrip()
        for n in range(len(self.needle) - 1, 2, -1):
            if tail.endswith(self.needle[:n]):
                s = len(tail) - n
                return [{"label": "person", "text": self.needle[:n],
                         "start": s, "end": len(tail), "score": 0.99}]
        return []


def test_name_after_the_model_word_limit_is_found():
    # 500 words in front of the name: one 4.000-character window would hold
    # all of it, but the model reads only its first 384 words.
    text = "word " * 500 + "Eleanor Whitfield signed."
    ents = gliner_detect(text, GLiNERConfig(), TruncatingStub("Eleanor Whitfield"))
    assert [text[e.start:e.end] for e in ents] == ["Eleanor Whitfield"]


def test_windows_never_exceed_the_model_word_limit():
    model = TruncatingStub("Eleanor Whitfield", max_len=50)
    text = "word " * 400 + "Eleanor Whitfield signed."
    ents = gliner_detect(text, GLiNERConfig(max_chunk_words=96), model)
    assert model.longest_input_words <= 50
    assert [text[e.start:e.end] for e in ents] == ["Eleanor Whitfield"]


def test_name_across_a_window_boundary_is_found_whole_once():
    cfg = GLiNERConfig(max_chunk_words=20, chunk_overlap_words=6)
    for lead in range(0, 40):
        text = "w " * lead + "Eleanor Whitfield" + " w" * 60
        ents = gliner_detect(text, cfg, CutAtEdgeStub("Eleanor Whitfield"))
        assert [text[e.start:e.end] for e in ents] == ["Eleanor Whitfield"], lead

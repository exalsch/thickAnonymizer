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
    ents = gliner_detect(text, GLiNERConfig(max_chunk_chars=40), FindStub("John"))
    spans = [(e.start, e.end) for e in ents]
    assert spans and len(spans) == len(set(spans))   # no duplicate global spans


def test_out_of_range_offsets_skipped():
    model = StubModel([{"label": "person", "text": "zz", "start": 99, "end": 101, "score": 0.9}])
    assert gliner_detect("short", GLiNERConfig(), model) == []

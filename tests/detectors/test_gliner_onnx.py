"""The torch-free GLiNER runner: input feeds, span decoding, offsets.

A stub tokenizer and a stub ONNX session stand in for the 1,16 GB model, so
these tests check the code around the network, not the network itself. The
real model is covered by tests/integration/test_gliner_real.py.
"""
import math
from types import SimpleNamespace

import numpy as np
import pytest

from thickanon.detectors.gliner_onnx import OnnxGliner

CONFIG = {"max_len": 384, "max_width": 12, "ent_token": "<<ENT>>", "sep_token": "<<SEP>>"}
LABELS = ["person", "location"]
TEXT = "Please call Eleanor Whitfield today"   # words 0..4, "Whitfield" is 2 subtokens


class StubTokenizer:
    """One token per word, except 'Whitfield', which becomes two subtokens."""

    def encode(self, words, is_pretokenized=True):
        assert is_pretokenized
        ids, word_ids = [1], [None]                       # [CLS]
        for index, word in enumerate(words):
            for _ in range(2 if word == "Whitfield" else 1):
                ids.append(100 + index)
                word_ids.append(index)
        ids.append(2)                                     # [SEP]
        word_ids.append(None)
        return SimpleNamespace(ids=ids, word_ids=word_ids)


class StubSession:
    """Returns logits of -10 everywhere except the cells set in hot."""

    def __init__(self, hot):
        self.hot, self.feeds = hot, None

    def get_inputs(self):
        names = ["input_ids", "attention_mask", "words_mask", "text_lengths", "span_idx", "span_mask"]
        return [SimpleNamespace(name=n) for n in names]

    def run(self, _outputs, feeds):
        self.feeds = feeds
        n = int(feeds["text_lengths"][0][0])
        logits = np.full((1, n, CONFIG["max_width"], len(LABELS)), -10.0, dtype=np.float32)
        for (start, width, cls), value in self.hot.items():
            logits[0, start, width, cls] = value
        return [logits]


def _model(hot):
    return OnnxGliner(CONFIG, StubTokenizer(), StubSession(hot))


def _sigmoid(x):
    return 1 / (1 + math.exp(-x))


def test_a_span_becomes_an_entity_with_character_offsets():
    # start word 2, width index 1 (two words), class 0 = person
    ents = _model({(2, 1, 0): 5.0}).predict_entities(TEXT, LABELS, threshold=0.5)
    assert len(ents) == 1
    e = ents[0]
    assert (e["start"], e["end"], e["text"], e["label"]) == (12, 29, "Eleanor Whitfield", "person")
    assert e["score"] == pytest.approx(_sigmoid(5.0), rel=1e-5)


def test_overlapping_spans_keep_only_the_higher_score():
    model = _model({(2, 1, 0): 5.0, (3, 0, 1): 6.0})
    ents = model.predict_entities(TEXT, LABELS, threshold=0.5)
    assert [(e["text"], e["label"]) for e in ents] == [("Whitfield", "location")]


def test_scores_below_the_threshold_are_dropped():
    assert _model({(2, 1, 0): -1.0}).predict_entities(TEXT, LABELS, threshold=0.5) == []


def test_spans_past_the_last_word_are_ignored():
    # start word 4 ("today") with width index 3 would end at word 7
    assert _model({(4, 3, 0): 9.0}).predict_entities(TEXT, LABELS, threshold=0.5) == []


def test_feeds_mark_the_first_subtoken_of_each_text_word():
    session = StubSession({})
    OnnxGliner(CONFIG, StubTokenizer(), session).predict_entities(TEXT, LABELS)
    feeds = session.feeds
    # [CLS], 5 prompt words (<<ENT>> person <<ENT>> location <<SEP>>),
    # Please call Eleanor Whitfield(2 subtokens) today, [SEP]
    assert feeds["words_mask"].tolist() == [[0, 0, 0, 0, 0, 0, 1, 2, 3, 4, 0, 5, 0]]
    assert feeds["text_lengths"].tolist() == [[5]]
    assert feeds["span_idx"].shape == (1, 5 * CONFIG["max_width"], 2)
    assert feeds["span_mask"].shape == (1, 5 * CONFIG["max_width"])
    assert feeds["span_mask"].sum() == sum(min(CONFIG["max_width"], 5 - s) for s in range(5))


def test_exposes_the_model_word_limit_for_windowing():
    assert _model({}).config.max_len == 384


def test_text_longer_than_the_word_limit_is_windowed_not_cut():
    model = OnnxGliner({**CONFIG, "max_len": 20}, StubTokenizer(), StubSession({}))
    text = "word " * 50 + "end"
    model.predict_entities(text, LABELS)
    # every call stayed within the limit
    assert int(model.session.feeds["text_lengths"][0][0]) <= 20


def test_empty_text_needs_no_model_call():
    session = StubSession({})
    assert OnnxGliner(CONFIG, StubTokenizer(), session).predict_entities("   ", LABELS) == []
    assert session.feeds is None

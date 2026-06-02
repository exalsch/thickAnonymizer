from thickanon.core.types import AnonymizeConfig, GLiNERConfig
from thickanon.detectors import gliner_model
from thickanon.detectors.engine import detect


class StubModel:
    def predict_entities(self, text, labels, threshold=0.5):
        i = text.find("John Carter")
        return ([{"label": "person", "text": "John Carter",
                  "start": i, "end": i + 11, "score": 0.9}] if i != -1 else [])


def test_gliner_branch_merges_regex_and_gliner(monkeypatch):
    calls = []

    def fake_load_model(cfg):
        calls.append(cfg)
        return StubModel()

    monkeypatch.setattr(gliner_model, "load_model", fake_load_model)
    text = "John Carter emailed jane@acme.com from 10.0.0.5"
    cfg = AnonymizeConfig(gliner=GLiNERConfig(enabled=True), low_threshold=0.35)
    ents = detect(text, cfg)
    # prove the GLiNER branch actually ran (not spaCy producing PERSON)
    assert calls, "gliner_model.load_model was not called — GLiNER branch not taken"
    labels = {e.entity_type for e in ents}
    assert {"PERSON", "EMAIL", "IP"} <= labels      # regex (EMAIL/IP) + GLiNER (PERSON)
    for e in ents:
        assert text[e.start:e.end] == e.text


def test_gliner_branch_does_not_load_spacy(monkeypatch):
    # When GLiNER is enabled, the spaCy analyzer must not be built.
    import thickanon.detectors.engine as eng
    monkeypatch.setattr(gliner_model, "load_model", lambda cfg: StubModel())
    monkeypatch.setattr(eng, "_base_analyzer",
                        lambda lang: (_ for _ in ()).throw(AssertionError("spaCy loaded")))
    cfg = AnonymizeConfig(gliner=GLiNERConfig(enabled=True), low_threshold=0.35)
    ents = detect("John Carter at 10.0.0.5", cfg)   # must not raise
    assert {"PERSON", "IP"} <= {e.entity_type for e in ents}


def test_gliner_disabled_uses_spacy_path():
    ents = detect("John at 10.0.0.1", AnonymizeConfig())
    assert {"IP"} <= {e.entity_type for e in ents}

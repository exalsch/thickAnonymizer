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


def test_gliner_name_across_the_4000_char_boundary_is_not_cut(monkeypatch):
    # The engine's outer 4.000-character windows exist for spaCy. In GLiNER
    # mode a window that ends inside a name must not leave a cut-off span
    # that hides the rest of the name.
    from tests.detectors.test_gliner_detect import CutAtEdgeStub

    monkeypatch.setattr(gliner_model, "load_model", lambda cfg: CutAtEdgeStub("Eleanor Whitfield"))
    cfg = AnonymizeConfig(gliner=GLiNERConfig(enabled=True, max_chunk_words=2000,
                                              chunk_overlap_words=10))
    for lead in range(3990, 4000):
        text = "x" * lead + " Eleanor Whitfield signed." + " y" * 50
        persons = [text[e.start:e.end] for e in detect(text, cfg) if e.entity_type == "PERSON"]
        assert persons == ["Eleanor Whitfield"], lead


def test_gliner_mode_reports_progress_per_window(monkeypatch):
    monkeypatch.setattr(gliner_model, "load_model", lambda cfg: StubModel())
    calls = []
    cfg = AnonymizeConfig(gliner=GLiNERConfig(enabled=True))
    detect("John Carter wrote. " * 300, cfg, progress=lambda d, t: calls.append((d, t)))
    assert len(calls) > 1
    assert calls[-1][0] == calls[-1][1]


def test_hostname_label_maps_to_the_host_token():
    from thickanon.detectors.normalize import normalize_type
    assert normalize_type("hostname") == "HOST"

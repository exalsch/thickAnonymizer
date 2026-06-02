from thickanon.core.types import AnonymizeConfig, LLMConfig
from thickanon.detectors import llm_model
from thickanon.detectors.engine import detect


def test_llm_branch_merges_regex_and_llm(monkeypatch):
    calls = []

    def fake_runner(prompt):
        calls.append(prompt)
        return '[{"type":"PERSON","text":"John Carter"}]'

    monkeypatch.setattr(llm_model, "load_runner", lambda cfg: fake_runner)

    text = "John Carter emailed jane@acme.com from 10.0.0.5"
    cfg = AnonymizeConfig(llm=LLMConfig(enabled=True), low_threshold=0.35)
    ents = detect(text, cfg)
    labels = {e.entity_type for e in ents}

    # load_runner must have been called (LLM branch active, not spaCy)
    assert calls, "load_runner was never called — LLM branch not reached"

    assert {"PERSON", "EMAIL", "IP"} <= labels       # regex + LLM both present
    for e in ents:
        assert text[e.start:e.end] == e.text          # offsets valid


def test_llm_disabled_uses_spacy_path():
    ents = detect("John at 10.0.0.1", AnonymizeConfig())
    assert {"IP"} <= {e.entity_type for e in ents}

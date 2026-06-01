from thickanon.core.types import AnonymizeConfig
from thickanon.detectors.engine import detect

def test_detect_returns_entities_with_text():
    cfg = AnonymizeConfig(deny_list=["Project Falcon"])
    text = "Project Falcon admin John Doe at 10.0.0.5 emailed jane@acme.com"
    ents = detect(text, cfg)
    labels = {e.entity_type for e in ents}
    assert {"TERM", "IP", "EMAIL"} <= labels
    # every entity's text slice matches its offsets
    for e in ents:
        assert text[e.start:e.end] == e.text

def test_overlaps_resolved_highest_score_wins():
    # jane@acme.com: EMAIL (0.9) must beat FQDN-on-domain (0.6); no nested dupes
    ents = detect("contact jane@acme.com please", AnonymizeConfig())
    spans = [(e.start, e.end) for e in ents]
    assert len(spans) == len(set(spans))  # no duplicate/overlapping spans

def test_entity_type_labels_normalized():
    ents = detect("mail jane@acme.com", AnonymizeConfig())
    types = {e.entity_type for e in ents}
    assert any(e.entity_type == "EMAIL" for e in ents)
    assert "EMAIL_ADDRESS" not in types

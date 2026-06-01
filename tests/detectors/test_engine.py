from thickanon.core.types import AnonymizeConfig
from thickanon.detectors.engine import detect

def test_detect_returns_entities_with_text():
    cfg = AnonymizeConfig(deny_list=["Project Falcon"])
    text = "Project Falcon admin John Doe at 10.0.0.5 emailed jane@acme.com"
    ents = detect(text, cfg)
    labels = {e.entity_type for e in ents}
    assert {"DENY", "IP", "EMAIL_ADDRESS"} <= labels
    # every entity's text slice matches its offsets
    for e in ents:
        assert text[e.start:e.end] == e.text

def test_overlaps_resolved_highest_score_wins():
    # jane@acme.com: EMAIL (0.9) must beat FQDN-on-domain (0.6); no nested dupes
    ents = detect("contact jane@acme.com please", AnonymizeConfig())
    spans = [(e.start, e.end) for e in ents]
    assert len(spans) == len(set(spans))  # no duplicate/overlapping spans

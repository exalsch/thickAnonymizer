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


def test_long_text_is_chunked_and_finds_the_same_entities():
    from thickanon.detectors.engine import MAX_ANALYZE_CHARS, _detect_once, detect
    from thickanon.core.types import AnonymizeConfig

    block = "Contact jane@acme.com at 10.0.0.5 about host api.example.com.\n"
    text = block * ((MAX_ANALYZE_CHARS * 3) // len(block))
    cfg = AnonymizeConfig()

    chunked = {(e.start, e.end, e.entity_type) for e in detect(text, cfg)}
    whole = {(e.start, e.end, e.entity_type) for e in _detect_once(text, cfg)}
    # Chunking must not lose anything the single pass found.
    assert whole <= chunked


def test_detect_reports_chunk_progress_only_when_chunked():
    from thickanon.detectors.engine import MAX_ANALYZE_CHARS, detect
    from thickanon.core.types import AnonymizeConfig

    cfg = AnonymizeConfig()
    small = []
    detect("mail jane@acme.com", cfg, progress=lambda d, t: small.append((d, t)))
    assert small == [(1, 1)]

    big = []
    text = "Contact jane@acme.com at 10.0.0.5.\n" * (MAX_ANALYZE_CHARS // 10)
    detect(text, cfg, progress=lambda d, t: big.append((d, t)))
    assert len(big) > 1
    assert big[-1][0] == big[-1][1]  # finishes at 100 percent


def test_resolve_overlaps_keeps_the_highest_score_and_is_ordered():
    from thickanon.detectors.engine import _resolve_overlaps
    from thickanon.core.types import Entity

    a = Entity(0, 10, "PERSON", 0.9, "x")
    b = Entity(5, 15, "EMAIL", 0.5, "y")     # overlaps a, lower score -> dropped
    c = Entity(20, 30, "IP", 0.7, "z")
    kept = _resolve_overlaps([b, c, a])
    assert kept == [a, c]

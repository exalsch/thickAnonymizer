from thickanon.detectors.llm import resolve_spans

def test_found_span_gets_correct_offsets_and_confidence():
    text = "Hi John, regards Berlin office"
    ents = resolve_spans(text, [{"type": "PERSON", "text": "John"}], confidence=0.5)
    assert len(ents) == 1
    e = ents[0]
    assert text[e.start:e.end] == "John" and e.entity_type == "PERSON" and e.score == 0.5

def test_hallucinated_span_dropped():
    text = "no names here"
    assert resolve_spans(text, [{"type": "PERSON", "text": "Zorptron"}], 0.5) == []

def test_multiple_occurrences_all_returned():
    text = "John and John"
    ents = resolve_spans(text, [{"type": "PERSON", "text": "John"}], 0.5)
    assert sorted((e.start, e.end) for e in ents) == [(0, 4), (9, 13)]

def test_type_normalized_and_base_offset_applied():
    ents = resolve_spans("jane@x.com", [{"type": "email address", "text": "jane@x.com"}], 0.5, base=100)
    assert ents[0].entity_type == "EMAIL" and ents[0].start == 100 and ents[0].end == 110

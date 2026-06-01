from thickanon.detectors.llm import parse_items

def test_parses_plain_json_array():
    items = parse_items('[{"type":"PERSON","text":"John"},{"type":"LOCATION","text":"Berlin"}]')
    assert items == [{"type": "PERSON", "text": "John"},
                     {"type": "LOCATION", "text": "Berlin"}]

def test_strips_code_fences():
    items = parse_items('```json\n[{"type":"PERSON","text":"Jo"}]\n```')
    assert items == [{"type": "PERSON", "text": "Jo"}]

def test_malformed_returns_empty():
    assert parse_items("not json at all") == []
    assert parse_items("") == []

def test_drops_items_missing_keys_or_wrong_types():
    raw = '[{"type":"PERSON","text":"A"},{"type":"PERSON"},{"text":"B"},{"type":1,"text":"C"}]'
    assert parse_items(raw) == [{"type": "PERSON", "text": "A"}]

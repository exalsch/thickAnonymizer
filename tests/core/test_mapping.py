from thickanon.core.mapping import MappingStore


def test_consistent_tokens():
    m = MappingStore()
    t1 = m.token_for("John Smith", "PERSON")
    t2 = m.token_for("John Smith", "PERSON")
    assert t1 == t2 == "[PERSON_1]"


def test_increments_per_type():
    m = MappingStore()
    assert m.token_for("10.0.0.1", "IP") == "[IP_1]"
    assert m.token_for("10.0.0.2", "IP") == "[IP_2]"
    assert m.token_for("John", "PERSON") == "[PERSON_1]"


def test_reverse_lookup():
    m = MappingStore()
    tok = m.token_for("db.acme.local", "HOST")
    assert m.value_for(tok) == "db.acme.local"
    assert m.value_for("[HOST_999]") is None


def test_load_or_new_continues_counters(tmp_path):
    path = tmp_path / "m.json"
    first = MappingStore()
    assert first.token_for("jane@acme.com", "EMAIL") == "[EMAIL_1]"
    first.save(path)

    second = MappingStore.load_or_new(path)
    assert second.token_for("bob@evil.com", "EMAIL") == "[EMAIL_2]"
    assert second.value_for("[EMAIL_1]") == "jane@acme.com"


def test_load_or_new_starts_fresh_when_absent(tmp_path):
    store = MappingStore.load_or_new(tmp_path / "nope.json")
    assert store.token_for("x@y.com", "EMAIL") == "[EMAIL_1]"

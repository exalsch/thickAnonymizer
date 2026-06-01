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

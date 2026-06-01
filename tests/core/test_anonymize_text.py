from thickanon.core.types import Entity
from thickanon.core.mapping import MappingStore
from thickanon.core.anonymize import apply_tokens


def test_replaces_spans_with_consistent_tokens():
    text = "John met John at 10.0.0.1"
    ents = [
        Entity(0, 4, "PERSON", 0.9, "John"),
        Entity(9, 13, "PERSON", 0.9, "John"),
        Entity(17, 25, "IP", 0.9, "10.0.0.1"),
    ]
    m = MappingStore()
    out = apply_tokens(text, ents, m)
    assert out == "[PERSON_1] met [PERSON_1] at [IP_1]"


def test_unsorted_entities_handled():
    text = "a@b.com and 10.0.0.1"
    ents = [Entity(12, 20, "IP", 0.9, "10.0.0.1"), Entity(0, 7, "EMAIL_ADDRESS", 0.9, "a@b.com")]
    out = apply_tokens(text, ents, MappingStore())
    assert out == "[EMAIL_ADDRESS_1] and [IP_1]"

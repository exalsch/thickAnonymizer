from thickanon.core.types import Entity
from thickanon.core.mapping import MappingStore
from thickanon.core.anonymize import apply_tokens, deanonymize


def test_roundtrip_restores_original():
    text = "John at 10.0.0.1 mailed jane@acme.com"
    ents = [
        Entity(0, 4, "PERSON", 0.9, "John"),
        Entity(8, 16, "IP", 0.9, "10.0.0.1"),
        Entity(24, 38, "EMAIL_ADDRESS", 0.9, "jane@acme.com"),
    ]
    m = MappingStore()
    anon = apply_tokens(text, ents, m)
    assert deanonymize(anon, m) == text


def test_deanonymize_ignores_unknown_tokens():
    m = MappingStore()
    m.token_for("John", "PERSON")
    assert deanonymize("hi [PERSON_1] and [GHOST_9]", m) == "hi John and [GHOST_9]"

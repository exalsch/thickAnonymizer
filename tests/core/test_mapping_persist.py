import pytest
from thickanon.core.mapping import MappingStore

def test_plaintext_roundtrip(tmp_path):
    m = MappingStore()
    m.token_for("John", "PERSON")
    p = tmp_path / "map.json"
    m.save(p)
    loaded = MappingStore.load(p)
    assert loaded.value_for("[PERSON_1]") == "John"
    assert loaded.token_for("John", "PERSON") == "[PERSON_1]"  # counter preserved

def test_encrypted_roundtrip(tmp_path):
    m = MappingStore()
    m.token_for("10.0.0.1", "IP")
    p = tmp_path / "map.enc"
    m.save(p, passphrase="hunter2")
    loaded = MappingStore.load(p, passphrase="hunter2")
    assert loaded.value_for("[IP_1]") == "10.0.0.1"

def test_wrong_passphrase_raises(tmp_path):
    m = MappingStore()
    m.token_for("10.0.0.1", "IP")
    p = tmp_path / "map.enc"
    m.save(p, passphrase="hunter2")
    with pytest.raises(ValueError):
        MappingStore.load(p, passphrase="wrong")

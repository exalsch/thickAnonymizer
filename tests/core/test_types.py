from thickanon.core.types import Entity, ReviewMode, AnonymizeConfig

def test_entity_fields():
    e = Entity(start=0, end=4, entity_type="PERSON", score=0.9, text="John")
    assert (e.start, e.end, e.entity_type, e.score, e.text) == (0, 4, "PERSON", 0.9, "John")

def test_review_modes_exist():
    assert {m.name for m in ReviewMode} == {"QUICK_REVIEW", "AUTO_REDACT", "AUTO_SKIP"}

def test_config_defaults():
    c = AnonymizeConfig()
    assert c.mode is ReviewMode.QUICK_REVIEW
    assert 0 < c.low_threshold <= c.high_threshold <= 1
    assert c.deny_list == []

from thickanon.core.types import AnonymizeConfig, GLiNERConfig, DEFAULT_GLINER_LABELS


def test_gliner_defaults():
    c = GLiNERConfig()
    assert c.enabled is False
    assert c.threshold == 0.5
    assert c.gpu is False
    assert c.max_chunk_chars > 0
    assert c.labels == DEFAULT_GLINER_LABELS
    assert isinstance(c.model_id, str) and c.model_id


def test_anonymizeconfig_has_optional_gliner():
    assert AnonymizeConfig().gliner is None
    assert AnonymizeConfig(gliner=GLiNERConfig(enabled=True)).gliner.enabled is True


def test_independent_label_lists():
    a, b = GLiNERConfig(), GLiNERConfig()
    a.labels.append("extra")
    assert "extra" not in b.labels

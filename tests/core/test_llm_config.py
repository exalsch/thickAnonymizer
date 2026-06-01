from thickanon.core.types import AnonymizeConfig, LLMConfig, DEFAULT_LLM_CATEGORIES

def test_llmconfig_defaults():
    c = LLMConfig()
    assert c.enabled is False
    assert c.n_gpu_layers == 0
    assert c.confidence == 0.5
    assert c.max_chunk_chars > 0
    assert c.categories == DEFAULT_LLM_CATEGORIES
    assert c.custom_instruction == ""

def test_anonymizeconfig_has_optional_llm():
    assert AnonymizeConfig().llm is None
    cfg = AnonymizeConfig(llm=LLMConfig(enabled=True))
    assert cfg.llm.enabled is True

def test_two_configs_have_independent_category_lists():
    a, b = LLMConfig(), LLMConfig()
    a.categories.append("EXTRA")
    assert "EXTRA" not in b.categories

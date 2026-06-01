import os, pytest
from thickanon.core.types import AnonymizeConfig, LLMConfig
from thickanon.detectors.engine import detect

pytestmark = pytest.mark.skipif(
    os.environ.get("THICKANON_LLM_IT") != "1",
    reason="set THICKANON_LLM_IT=1 to run the real-model integration test",
)

def test_real_model_detects_name():
    cfg = AnonymizeConfig(llm=LLMConfig(enabled=True))  # downloads default model
    ents = detect("Please contact Dr. Eleanor Whitfield about the case.", cfg)
    assert any(e.entity_type == "PERSON" and "Whitfield" in e.text for e in ents)

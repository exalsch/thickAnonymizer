import os
import pytest
from thickanon.core.types import AnonymizeConfig, DEFAULT_GLINER_MODEL_ID, GLiNERConfig
from thickanon.detectors.engine import detect


def _model_is_cached() -> bool:
    """True when gliner is installed and the default model is in the local HF cache.

    A dependency update once broke model loading (a transitive dependency
    disappeared) while every stub-based test stayed green. Running the real
    model whenever it is already on disk catches that without a download.
    """
    try:
        import gliner  # noqa: F401
        from huggingface_hub import try_to_load_from_cache
    except ImportError:
        return False
    found = try_to_load_from_cache(DEFAULT_GLINER_MODEL_ID, "gliner_config.json")
    return isinstance(found, str)


pytestmark = pytest.mark.skipif(
    os.environ.get("THICKANON_GLINER_IT") != "1" and not _model_is_cached(),
    reason="default GLiNER model not cached; set THICKANON_GLINER_IT=1 to download and run",
)


def test_real_model_detects_name():
    cfg = AnonymizeConfig(gliner=GLiNERConfig(enabled=True))
    ents = detect("Please contact Dr. Eleanor Whitfield about the case.", cfg)
    assert any(e.entity_type == "PERSON" and "Whitfield" in e.text for e in ents)


def test_real_model_finds_a_name_after_its_word_limit():
    # The default model reads only 384 words per call. Before the input was
    # windowed by words, a name after word 384 of a 4.000-character window was
    # never seen.
    filler = "The batch job finished and the report was sent to the archive. " * 45
    text = filler + "Please contact Dr. Eleanor Whitfield about the case."
    cfg = AnonymizeConfig(gliner=GLiNERConfig(enabled=True))
    ents = detect(text, cfg)
    assert any(e.entity_type == "PERSON" and "Whitfield" in e.text for e in ents)

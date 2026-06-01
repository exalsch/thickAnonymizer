from thickanon.core.types import LLMConfig
from thickanon.detectors.llm import llm_detect


def test_llm_detect_with_stub_runner():
    text = "Patient John Carter visited Berlin clinic"

    def runner(prompt):  # ignores prompt, returns canned JSON
        return '[{"type":"PERSON","text":"John Carter"},{"type":"LOCATION","text":"Berlin"}]'

    cfg = LLMConfig(enabled=True, confidence=0.5, categories=["PERSON", "LOCATION"])
    ents = llm_detect(text, cfg, runner=runner)
    by_type = {e.entity_type: e for e in ents}
    assert text[by_type["PERSON"].start:by_type["PERSON"].end] == "John Carter"
    assert by_type["LOCATION"].score == 0.5


def test_llm_detect_dedupes_across_chunks():
    text = "John " * 50  # long enough to chunk; overlaps would double-count

    def runner(prompt):
        return '[{"type":"PERSON","text":"John"}]'

    cfg = LLMConfig(enabled=True, max_chunk_chars=40)
    ents = llm_detect(text, cfg, runner=runner)
    spans = [(e.start, e.end) for e in ents]
    assert len(spans) == len(set(spans))  # no duplicate spans from overlap

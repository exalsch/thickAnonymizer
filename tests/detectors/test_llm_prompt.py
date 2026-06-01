from thickanon.detectors.llm import build_prompt

def test_prompt_lists_categories_and_text():
    p = build_prompt("John lives in Berlin", ["PERSON", "LOCATION"], "")
    assert "PERSON" in p and "LOCATION" in p
    assert "John lives in Berlin" in p
    assert "JSON" in p  # instructs JSON output

def test_prompt_includes_custom_instruction():
    p = build_prompt("x", ["PERSON"], "Treat internal codenames as sensitive.")
    assert "internal codenames" in p

import pytest
from thickanon.io.text import read_fragments, write_fragments

def test_text_single_fragment_roundtrip(tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("hello 10.0.0.1 world", encoding="utf-8")
    frags = read_fragments(p)
    assert frags == ["hello 10.0.0.1 world"]
    write_fragments(p, ["hello [IP_1] world"])
    assert p.read_text(encoding="utf-8") == "hello [IP_1] world"


def test_text_write_wrong_fragment_count_raises(tmp_path):
    """Change B: write_fragments must raise ValueError when not exactly 1 fragment."""
    p = tmp_path / "b.txt"
    p.write_text("hello world", encoding="utf-8")

    with pytest.raises(ValueError):
        write_fragments(p, [])  # 0 instead of 1

    with pytest.raises(ValueError):
        write_fragments(p, ["a", "b"])  # 2 instead of 1

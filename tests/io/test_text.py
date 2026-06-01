from thickanon.io.text import read_fragments, write_fragments

def test_text_single_fragment_roundtrip(tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("hello 10.0.0.1 world", encoding="utf-8")
    frags = read_fragments(p)
    assert frags == ["hello 10.0.0.1 world"]
    write_fragments(p, ["hello [IP_1] world"])
    assert p.read_text(encoding="utf-8") == "hello [IP_1] world"

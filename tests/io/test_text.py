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


def test_text_preserves_lf_line_endings(tmp_path):
    """A LF file must come back as a LF file.

    Python translates line endings on both read and write unless told not to,
    so on Windows an anonymize/de-anonymize round trip used to hand back a file
    whose every line had changed. The tool promises to rewrite only the spans
    it detected, so the endings have to survive untouched.
    """
    p = tmp_path / "unix.txt"
    p.write_bytes(b"alpha 10.0.0.1\nbeta\n")

    assert read_fragments(p) == ["alpha 10.0.0.1\nbeta\n"]
    write_fragments(p, ["alpha [IP_1]\nbeta\n"])
    assert p.read_bytes() == b"alpha [IP_1]\nbeta\n"


def test_text_preserves_crlf_line_endings(tmp_path):
    """The same guarantee in the other direction: CRLF stays CRLF."""
    p = tmp_path / "dos.txt"
    p.write_bytes(b"alpha 10.0.0.1\r\nbeta\r\n")

    assert read_fragments(p) == ["alpha 10.0.0.1\r\nbeta\r\n"]
    write_fragments(p, ["alpha [IP_1]\r\nbeta\r\n"])
    assert p.read_bytes() == b"alpha [IP_1]\r\nbeta\r\n"


def test_text_preserves_mixed_line_endings(tmp_path):
    """Mixed endings must not be silently normalised to one style."""
    p = tmp_path / "mixed.txt"
    p.write_bytes(b"alpha\r\nbeta\ngamma\r\n")

    frags = read_fragments(p)
    assert frags == ["alpha\r\nbeta\ngamma\r\n"]
    write_fragments(p, frags)
    assert p.read_bytes() == b"alpha\r\nbeta\ngamma\r\n"

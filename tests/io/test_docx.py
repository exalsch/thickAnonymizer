import pytest
from docx import Document
from thickanon.io.docx import read_fragments, write_fragments


def test_docx_fragment_roundtrip(tmp_path):
    p = tmp_path / "d.docx"
    doc = Document()
    doc.add_paragraph("Contact John at 10.0.0.1")
    doc.add_paragraph("Second line")
    doc.save(p)

    frags = read_fragments(p)
    assert frags == ["Contact John at 10.0.0.1", "Second line"]

    write_fragments(p, ["Contact [PERSON_1] at [IP_1]", "Second line"])
    reread = read_fragments(p)
    assert reread == ["Contact [PERSON_1] at [IP_1]", "Second line"]


def test_docx_write_wrong_fragment_count_raises(tmp_path):
    """Change B: write_fragments must raise ValueError on count mismatch."""
    p = tmp_path / "mismatch.docx"
    doc = Document()
    doc.add_paragraph("Line one")
    doc.add_paragraph("Line two")
    doc.save(p)

    # 2 paragraphs but only 1 fragment supplied
    with pytest.raises(ValueError):
        write_fragments(p, ["[REDACTED]"])

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

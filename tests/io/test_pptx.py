import pytest
from pptx import Presentation
from pptx.util import Inches
from thickanon.io.pptx import read_fragments, write_fragments


def test_pptx_roundtrip(tmp_path):
    p = tmp_path / "p.pptx"
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[5])
    box = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(4), Inches(1))
    box.text_frame.paragraphs[0].add_run().text = "John at 10.0.0.1"
    prs.save(p)

    assert read_fragments(p) == ["John at 10.0.0.1"]
    write_fragments(p, ["[PERSON_1] at [IP_1]"])
    assert read_fragments(p) == ["[PERSON_1] at [IP_1]"]


def test_pptx_write_wrong_fragment_count_raises(tmp_path):
    """Change B: write_fragments must raise ValueError on count mismatch."""
    p = tmp_path / "mismatch.pptx"
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[5])
    box = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(4), Inches(1))
    box.text_frame.paragraphs[0].add_run().text = "Sensitive data"
    prs.save(p)

    # 1 fragment exists but 0 supplied
    with pytest.raises(ValueError):
        write_fragments(p, [])

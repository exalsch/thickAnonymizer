from pptx import Presentation


def _paragraphs(prs):
    for slide in prs.slides:
        for shape in slide.shapes:
            if shape.has_text_frame:
                for para in shape.text_frame.paragraphs:
                    if para.runs:
                        yield para


def _para_text(paragraph) -> str:
    return "".join(run.text for run in paragraph.runs)


def read_fragments(path) -> list[str]:
    prs = Presentation(str(path))
    return [_para_text(p) for p in _paragraphs(prs)]


def write_fragments(path, fragments: list[str]) -> None:
    prs = Presentation(str(path))
    for paragraph, new_text in zip(_paragraphs(prs), fragments):
        if _para_text(paragraph) == new_text:
            continue
        if paragraph.runs:
            paragraph.runs[0].text = new_text
            for run in paragraph.runs[1:]:
                run.text = ""
    prs.save(str(path))

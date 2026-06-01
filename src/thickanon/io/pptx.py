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
    targets = list(_paragraphs(prs))
    if len(fragments) != len(targets):
        raise ValueError(
            f"Fragment count mismatch: expected {len(targets)} fragments, "
            f"got {len(fragments)}"
        )
    for paragraph, new_text in zip(targets, fragments):
        if _para_text(paragraph) == new_text:
            continue
        if paragraph.runs:
            paragraph.runs[0].text = new_text
            for run in paragraph.runs[1:]:
                run.text = ""
    prs.save(str(path))

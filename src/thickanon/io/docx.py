from docx import Document


def _iter_paragraphs(doc):
    yield from doc.paragraphs
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                yield from cell.paragraphs


def read_fragments(path) -> list[str]:
    doc = Document(str(path))
    return [p.text for p in _iter_paragraphs(doc)]


def _set_paragraph_text(paragraph, new_text: str) -> None:
    if paragraph.runs:
        paragraph.runs[0].text = new_text
        for run in paragraph.runs[1:]:
            run.text = ""
    elif new_text:
        paragraph.add_run(new_text)


def write_fragments(path, fragments: list[str]) -> None:
    doc = Document(str(path))
    targets = list(_iter_paragraphs(doc))
    if len(fragments) != len(targets):
        raise ValueError(
            f"Fragment count mismatch: expected {len(targets)} fragments, "
            f"got {len(fragments)}"
        )
    for paragraph, new_text in zip(targets, fragments):
        if paragraph.text != new_text:
            _set_paragraph_text(paragraph, new_text)
    doc.save(str(path))

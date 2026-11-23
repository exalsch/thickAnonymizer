"""Every part of an Office file that holds text must be anonymized.

The builders put personal data into headers, footers, text boxes, tracked
changes, comments, notes, charts, sheet names, formulas, link targets and the
document properties. After the fragments are anonymized and written back, no
part of the file, embedded files included, may still contain it.
"""
import pytest

from thickanon.io import docx as docx_io, pptx as pptx_io, xlsx as xlsx_io
from tests.io.office_builders import (
    EMAIL, IP, NAME, anonymize_fragments, build_docx, build_pptx, build_xlsx,
    deanonymize_fragments, leaks,
)

FORMATS = [
    ("docx", build_docx, docx_io),
    ("xlsx", build_xlsx, xlsx_io),
    ("pptx", build_pptx, pptx_io),
]


@pytest.mark.parametrize("ext,build,handler", FORMATS, ids=[f[0] for f in FORMATS])
def test_no_part_keeps_personal_data(tmp_path, ext, build, handler):
    path = build(tmp_path / f"leaky.{ext}")
    assert leaks(path), "the builder must put personal data into the file"

    handler.write_fragments(path, anonymize_fragments(handler.read_fragments(path)))

    assert leaks(path) == []


@pytest.mark.parametrize("ext,build,handler", FORMATS, ids=[f[0] for f in FORMATS])
def test_deanonymize_restores_every_fragment(tmp_path, ext, build, handler):
    path = build(tmp_path / f"roundtrip.{ext}")
    original = handler.read_fragments(path)

    handler.write_fragments(path, anonymize_fragments(original))
    handler.write_fragments(path, deanonymize_fragments(handler.read_fragments(path)))

    assert handler.read_fragments(path) == original


def test_docx_reads_every_text_part(tmp_path):
    frags = docx_io.read_fragments(build_docx(tmp_path / "parts.docx"))
    for expected in [
        f"Body mentions {NAME}.",
        f"Header: {EMAIL}",
        f"Footer {IP}",
        f"Nested {NAME}",
        f"Box {NAME}",
        f"SDT {IP}",
        f"deleted {NAME}",
        f"Ask {NAME}",
        f"mailto:{EMAIL}",
    ]:
        assert expected in frags, expected


def test_docx_hyperlink_text_is_read_once_and_not_duplicated(tmp_path):
    path = build_docx(tmp_path / "link.docx")
    assert f"Mail: {EMAIL} please." in docx_io.read_fragments(path)

    docx_io.write_fragments(path, anonymize_fragments(docx_io.read_fragments(path)))
    docx_io.write_fragments(path, deanonymize_fragments(docx_io.read_fragments(path)))

    from docx import Document
    body = "\n".join(p.text for p in Document(str(path)).paragraphs)
    assert body.count(EMAIL) == 1


def test_docx_keeps_the_formatting_of_runs_it_does_not_change(tmp_path):
    from docx import Document
    path = tmp_path / "fmt.docx"
    doc = Document()
    p = doc.add_paragraph()
    p.add_run("Bold intro ").bold = True
    p.add_run(f"then {NAME} at")
    p.add_run(" italic tail.").italic = True
    doc.save(path)

    docx_io.write_fragments(path, anonymize_fragments(docx_io.read_fragments(path)))

    runs = Document(str(path)).paragraphs[0].runs
    assert [(r.text, bool(r.bold), bool(r.italic)) for r in runs] == [
        ("Bold intro ", True, False),
        ("then [PERSON_1] at", False, False),
        (" italic tail.", False, True),
    ]


def test_docx_clears_author_and_document_properties(tmp_path):
    from docx import Document
    path = build_docx(tmp_path / "props.docx")
    docx_io.write_fragments(path, docx_io.read_fragments(path))
    props = Document(str(path)).core_properties
    assert (props.author, props.last_modified_by, props.title, props.comments) == ("", "", "", "")


def test_xlsx_reads_every_text_part(tmp_path):
    frags = xlsx_io.read_fragments(build_xlsx(tmp_path / "parts.xlsx"))
    for expected in [
        NAME,                    # the sheet name
        f"Contact {EMAIL}",
        f"=== {IP} ===",
        f"Call {NAME}",          # cell comment
        f"Owner {NAME}",         # header, without its &C code
        IP,                      # footer
        f"mailto:{EMAIL}",       # hyperlink target and formula literal
        f"{NAME},Other",         # data validation list literal
    ]:
        assert expected in frags, expected


def test_xlsx_renamed_sheet_keeps_its_references(tmp_path):
    from openpyxl import load_workbook
    path = build_xlsx(tmp_path / "rename.xlsx")

    xlsx_io.write_fragments(path, anonymize_fragments(xlsx_io.read_fragments(path)))

    wb = load_workbook(path)
    # Excel forbids [ and ] in sheet names, so the token is stored with ⟦ ⟧.
    assert wb.sheetnames[0] == "⟦PERSON_1⟧"
    assert wb["Summary"]["B1"].value == "='⟦PERSON_1⟧'!A1"
    assert wb.defined_names["owner"].attr_text == "'⟦PERSON_1⟧'!$A$1"
    assert "[PERSON_1]" in xlsx_io.read_fragments(path)

    xlsx_io.write_fragments(path, deanonymize_fragments(xlsx_io.read_fragments(path)))

    wb = load_workbook(path)
    assert wb.sheetnames[0] == NAME
    assert wb["Summary"]["B1"].value == f"='{NAME}'!A1"
    assert wb.defined_names["owner"].attr_text == f"'{NAME}'!$A$1"


def test_xlsx_text_that_starts_with_equals_stays_text(tmp_path):
    from openpyxl import load_workbook
    path = build_xlsx(tmp_path / "eq.xlsx")
    xlsx_io.write_fragments(path, anonymize_fragments(xlsx_io.read_fragments(path)))
    cell = load_workbook(path).worksheets[0]["A3"]
    assert (cell.value, cell.data_type) == ("=== [IP_1] ===", "s")


def test_xlsx_sheet_name_longer_than_excel_allows_is_refused(tmp_path):
    from openpyxl import Workbook
    path = tmp_path / "long.xlsx"
    wb = Workbook()
    wb.active.title = "Bo Li quarterly budget 2026"
    wb.save(path)
    frags = xlsx_io.read_fragments(path)
    frags[frags.index("Bo Li quarterly budget 2026")] = "[PERSON_12] quarterly budget 2026"
    with pytest.raises(ValueError, match="31"):
        xlsx_io.write_fragments(path, frags)


def test_pptx_reads_every_text_part(tmp_path):
    frags = pptx_io.read_fragments(build_pptx(tmp_path / "parts.pptx"))
    for expected in [
        f"Grouped {NAME}",
        f"Server {IP}",
        f"Notes: {EMAIL}",
        f"mailto:{EMAIL}",
        NAME,                    # chart category, in the chart and its embedded workbook
    ]:
        assert expected in frags, expected


def test_link_targets_stay_valid_uris(tmp_path):
    import zipfile
    path = build_docx(tmp_path / "uri.docx")
    docx_io.write_fragments(path, anonymize_fragments(docx_io.read_fragments(path)))

    with zipfile.ZipFile(path) as z:
        rels = z.read("word/_rels/document.xml.rels").decode()
    # [ and ] are reserved in a URI, so the token is stored percent-encoded
    assert 'Target="mailto:%5BEMAIL_1%5D"' in rels
    assert "mailto:[EMAIL_1]" in docx_io.read_fragments(path)


def test_embedded_workbook_sheet_rename_updates_the_chart(tmp_path):
    import zipfile
    from pptx import Presentation
    from pptx.chart.data import CategoryChartData
    from pptx.enum.chart import XL_CHART_TYPE
    from pptx.util import Inches
    from tests.io.office_builders import TOKENS

    path = tmp_path / "chart.pptx"
    prs = Presentation()
    data = CategoryChartData()
    data.categories = ["a", "b"]
    data.add_series("Hours", (1, 2))
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    slide.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(1), Inches(1),
                           Inches(4), Inches(3), data)
    prs.save(path)

    frags = pptx_io.read_fragments(path)
    frags[frags.index("Sheet1")] = TOKENS[NAME]
    pptx_io.write_fragments(path, frags)

    with zipfile.ZipFile(path) as z:
        chart = next(z.read(n).decode() for n in z.namelist() if n.startswith("ppt/charts/chart"))
    assert "Sheet1!" not in chart
    assert "'⟦PERSON_1⟧'!" in chart

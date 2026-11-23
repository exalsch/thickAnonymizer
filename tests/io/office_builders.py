"""Office files with personal data in every part a reader can reach.

Each builder puts NAME, EMAIL and IP into text that thickanon must anonymize,
and AUTHOR only into author or metadata fields, which thickanon must clear on
write even though no detector ever sees them.
"""
import zipfile

NAME = "Eleanor Whitfield"
EMAIL = "eleanor.whitfield@example.com"
IP = "10.20.30.40"
AUTHOR = "ewhitfield"
TOKENS = {NAME: "[PERSON_1]", EMAIL: "[EMAIL_1]", IP: "[IP_1]"}

# "hitfield" is in NAME, EMAIL and AUTHOR, in any letter case of the first W.
LEAK_MARKERS = [b"hitfield", IP.encode()]


def anonymize_fragments(fragments):
    out = []
    for fragment in fragments:
        for value, token in TOKENS.items():
            fragment = fragment.replace(value, token)
        out.append(fragment)
    return out


def deanonymize_fragments(fragments):
    out = []
    for fragment in fragments:
        for value, token in TOKENS.items():
            fragment = fragment.replace(token, value)
        out.append(fragment)
    return out


def _entries(data: bytes, prefix=""):
    import io
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for name in z.namelist():
            body = z.read(name)
            yield prefix + name, body
            if name.lower().endswith((".xlsx", ".docx", ".pptx")):
                yield from _entries(body, prefix + name + "!")


def leaks(path):
    """Every (part, marker) where personal data survived, embedded files included."""
    found = []
    for name, body in _entries(path.read_bytes()):
        for marker in LEAK_MARKERS:
            if marker in body:
                found.append((name, marker.decode()))
    return found


def build_docx(path):
    from docx import Document
    from docx.opc.constants import RELATIONSHIP_TYPE as RT
    from docx.oxml import parse_xml
    from docx.oxml.ns import nsdecls

    doc = Document()
    doc.add_paragraph(f"Body mentions {NAME}.")

    section = doc.sections[0]
    section.header.paragraphs[0].text = f"Header: {EMAIL}"
    section.footer.paragraphs[0].text = f"Footer {IP}"

    outer = doc.add_table(rows=1, cols=1)
    inner = outer.cell(0, 0).add_table(rows=1, cols=1)
    inner.cell(0, 0).paragraphs[0].text = f"Nested {NAME}"

    body = doc.element.body
    sect_pr = body[-1]

    textbox = doc.add_paragraph()
    textbox._p.append(parse_xml(
        f'<w:r {nsdecls("w")} xmlns:v="urn:schemas-microsoft-com:vml"><w:pict><v:shape>'
        f'<v:textbox><w:txbxContent><w:p><w:r><w:t>Box {NAME}</w:t></w:r></w:p>'
        f'</w:txbxContent></v:textbox></v:shape></w:pict></w:r>'))

    sect_pr.addprevious(parse_xml(
        f'<w:sdt {nsdecls("w")}><w:sdtContent><w:p><w:r><w:t>SDT {IP}</w:t></w:r></w:p>'
        f'</w:sdtContent></w:sdt>'))

    tracked = doc.add_paragraph()
    tracked._p.append(parse_xml(
        f'<w:ins {nsdecls("w")} w:id="901" w:author="{AUTHOR}" w:date="2026-11-23T00:00:00Z">'
        f'<w:r><w:t xml:space="preserve">inserted {EMAIL} </w:t></w:r></w:ins>'))
    tracked._p.append(parse_xml(
        f'<w:del {nsdecls("w")} w:id="902" w:author="{AUTHOR}" w:date="2026-11-23T00:00:00Z">'
        f'<w:r><w:delText>deleted {NAME}</w:delText></w:r></w:del>'))

    link = doc.add_paragraph("Mail: ")
    r_id = doc.part.relate_to(f"mailto:{EMAIL}", RT.HYPERLINK, is_external=True)
    link._p.append(parse_xml(
        f'<w:hyperlink {nsdecls("w", "r")} r:id="{r_id}"><w:r><w:t>{EMAIL}</w:t></w:r>'
        f'</w:hyperlink>'))
    link.add_run(" please.")

    commented = doc.add_paragraph("See the comment.")
    doc.add_comment(commented.runs[0], text=f"Ask {NAME}", author=AUTHOR, initials="EW")

    props = doc.core_properties
    props.author = AUTHOR
    props.last_modified_by = AUTHOR
    props.title = f"Report for {NAME}"
    props.comments = EMAIL
    doc.save(path)
    return path


def build_xlsx(path):
    from openpyxl import Workbook
    from openpyxl.comments import Comment
    from openpyxl.workbook.defined_name import DefinedName
    from openpyxl.worksheet.datavalidation import DataValidation

    wb = Workbook()
    ws = wb.active
    ws.title = NAME
    ws["A1"] = f"Contact {EMAIL}"
    ws["A2"] = "mail"
    ws["A2"].hyperlink = f"mailto:{EMAIL}"
    ws["A3"].value = f"=== {IP} ==="
    ws["A3"].data_type = "s"
    ws["A4"] = "commented"
    ws["A4"].comment = Comment(f"Call {NAME}", AUTHOR)
    ws.oddHeader.center.text = f"Owner {NAME}"
    ws.oddFooter.left.text = IP
    dv = DataValidation(type="list", formula1=f'"{NAME},Other"')
    ws.add_data_validation(dv)
    dv.add("B1")

    summary = wb.create_sheet("Summary")
    summary["B1"] = f"='{NAME}'!A1"
    summary["B2"] = f'=HYPERLINK("mailto:{EMAIL}","{NAME}")'

    wb.defined_names["owner"] = DefinedName("owner", attr_text=f"'{NAME}'!$A$1")
    wb.properties.creator = AUTHOR
    wb.properties.lastModifiedBy = AUTHOR
    wb.properties.title = NAME
    wb.save(path)
    return path


def build_pptx(path):
    from pptx import Presentation
    from pptx.chart.data import CategoryChartData
    from pptx.enum.chart import XL_CHART_TYPE
    from pptx.util import Inches

    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])

    group = slide.shapes.add_group_shape()
    box = group.shapes.add_textbox(Inches(1), Inches(1), Inches(4), Inches(1))
    box.text_frame.text = f"Grouped {NAME}"

    table = slide.shapes.add_table(1, 1, Inches(1), Inches(2), Inches(4), Inches(1)).table
    table.cell(0, 0).text = f"Server {IP}"

    linked = slide.shapes.add_textbox(Inches(1), Inches(3), Inches(4), Inches(1))
    run = linked.text_frame.paragraphs[0].add_run()
    run.text = "mail me"
    run.hyperlink.address = f"mailto:{EMAIL}"

    data = CategoryChartData()
    data.categories = [NAME, "Other"]
    data.add_series("Hours", (3, 4))
    slide.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(1), Inches(4),
                           Inches(4), Inches(2), data)

    slide.notes_slide.notes_text_frame.text = f"Notes: {EMAIL}"

    prs.core_properties.author = AUTHOR
    prs.core_properties.last_modified_by = AUTHOR
    prs.core_properties.title = NAME
    prs.save(path)
    return path

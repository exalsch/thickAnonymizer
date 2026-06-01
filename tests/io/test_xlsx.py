from openpyxl import Workbook, load_workbook
from thickanon.io.xlsx import read_fragments, write_fragments


def test_xlsx_string_cells_roundtrip(tmp_path):
    p = tmp_path / "s.xlsx"
    wb = Workbook(); ws = wb.active
    ws["A1"] = "John Doe"; ws["A2"] = 42; ws["A3"] = "10.0.0.1"
    wb.save(p)

    assert read_fragments(p) == ["John Doe", "10.0.0.1"]

    write_fragments(p, ["[PERSON_1]", "[IP_1]"])
    wb2 = load_workbook(p)
    assert wb2.active["A1"].value == "[PERSON_1]"
    assert wb2.active["A2"].value == 42
    assert wb2.active["A3"].value == "[IP_1]"

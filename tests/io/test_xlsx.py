import pytest
from openpyxl import Workbook, load_workbook
from thickanon.io.xlsx import read_fragments, write_fragments


def test_xlsx_string_cells_roundtrip(tmp_path):
    p = tmp_path / "s.xlsx"
    wb = Workbook(); ws = wb.active
    ws["A1"] = "John Doe"; ws["A2"] = 42; ws["A3"] = "10.0.0.1"
    wb.save(p)

    # shared strings first, then the sheet name from workbook.xml
    assert read_fragments(p) == ["John Doe", "10.0.0.1", "Sheet"]

    write_fragments(p, ["[PERSON_1]", "[IP_1]", "Sheet"])
    wb2 = load_workbook(p)
    assert wb2.active["A1"].value == "[PERSON_1]"
    assert wb2.active["A2"].value == 42
    assert wb2.active["A3"].value == "[IP_1]"


def test_xlsx_skips_formula_cells(tmp_path):
    """Change A: formula cells must be excluded from read and not overwritten."""
    p = tmp_path / "formula.xlsx"
    wb = Workbook(); ws = wb.active
    ws["A1"] = "John Doe"   # string → must be read
    ws["A2"] = 42            # number → excluded
    ws["A3"] = "=A1"         # formula → must be excluded
    wb.save(p)

    assert read_fragments(p) == ["John Doe", "Sheet"]

    write_fragments(p, ["[PERSON_1]", "Sheet"])
    wb2 = load_workbook(p)
    assert wb2.active["A1"].value == "[PERSON_1]"
    assert wb2.active["A2"].value == 42
    # formula must still start with "=" (not overwritten with literal text)
    assert str(wb2.active["A3"].value).startswith("=")


def test_xlsx_write_wrong_fragment_count_raises(tmp_path):
    """Change B: write_fragments must raise ValueError on count mismatch."""
    p = tmp_path / "mismatch.xlsx"
    wb = Workbook(); ws = wb.active
    ws["A1"] = "John Doe"; ws["A2"] = "Jane Doe"
    wb.save(p)

    # 2 string cells but 0 fragments supplied
    with pytest.raises(ValueError):
        write_fragments(p, [])

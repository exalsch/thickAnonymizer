from openpyxl import load_workbook


def _string_cells(wb):
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for cell in row:
                if isinstance(cell.value, str) and cell.value.strip():
                    yield cell


def read_fragments(path) -> list[str]:
    wb = load_workbook(str(path))
    return [cell.value for cell in _string_cells(wb)]


def write_fragments(path, fragments: list[str]) -> None:
    wb = load_workbook(str(path))
    for cell, new_text in zip(_string_cells(wb), fragments):
        cell.value = new_text
    wb.save(str(path))

from pathlib import Path
from thickanon.io import text, docx, xlsx, pptx


class UnsupportedFileType(Exception):
    pass


_TEXT_EXTS = {
    ".txt", ".md", ".csv", ".py", ".js", ".ts", ".json", ".yaml", ".yml",
    ".log", ".ini", ".cfg", ".html", ".xml", ".sh", ".ps1", ".java", ".go",
}


def get_handler(path):
    ext = Path(path).suffix.lower()
    if ext in _TEXT_EXTS:
        return text
    if ext == ".docx":
        return docx
    if ext == ".xlsx":
        return xlsx
    if ext == ".pptx":
        return pptx
    raise UnsupportedFileType(ext)

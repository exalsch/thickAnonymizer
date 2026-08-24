from pathlib import Path
from thickanon.io import text, docx, xlsx, pptx


class UnsupportedFileType(Exception):
    pass


_TEXT_EXTS = {
    ".txt", ".md", ".csv", ".py", ".js", ".ts", ".json", ".yaml", ".yml",
    ".log", ".ini", ".cfg", ".html", ".xml", ".sh", ".ps1", ".java", ".go",
}


_OFFICE_HANDLERS = {".docx": docx, ".xlsx": xlsx, ".pptx": pptx}


def supported_extensions() -> list[str]:
    """Every extension this tool can read and write, for display in the UI."""
    return sorted(_TEXT_EXTS | set(_OFFICE_HANDLERS))


def get_handler(path):
    ext = Path(path).suffix.lower()
    if ext in _TEXT_EXTS:
        return text
    if ext in _OFFICE_HANDLERS:
        return _OFFICE_HANDLERS[ext]
    raise UnsupportedFileType(ext)

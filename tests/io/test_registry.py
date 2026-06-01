import pytest
from thickanon.io.registry import get_handler, UnsupportedFileType


def test_known_extensions():
    for ext in [".txt", ".md", ".csv", ".py", ".docx", ".xlsx", ".pptx"]:
        h = get_handler(f"file{ext}")
        assert hasattr(h, "read_fragments") and hasattr(h, "write_fragments")


def test_unsupported_raises():
    with pytest.raises(UnsupportedFileType):
        get_handler("photo.png")

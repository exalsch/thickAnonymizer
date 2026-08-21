import re
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[2] / "src" / "thickanon" / "ui" / "web"

REQUIRED_IDS = [
    # files
    "drop", "browse-files", "browse-folder", "clear-files", "files", "file-count",
    # settings
    "mode", "root", "mapping", "choose-mapping", "backup-enabled", "backup",
    "choose-backup", "pass", "pass-confirm", "pass-confirm-row", "deny",
    # advanced
    "advanced", "gliner", "gliner-note", "gliner-labels", "gliner-threshold",
    "gliner-gpu", "download-model",
    # actions
    "scan", "deanonymize", "cancel",
    # progress
    "progress", "progress-bar", "progress-label", "progress-file",
    # review
    "review", "review-groups", "review-count", "review-approve-all",
    "review-reject-all", "review-apply", "review-cancel", "review-truncated",
    # report
    "report", "report-headline", "report-types", "report-files", "report-skipped",
    "report-residual", "report-copy", "report-save",
    # chrome
    "version", "theme-toggle", "banner",
]


def _read(name: str) -> str:
    return (WEB / name).read_text(encoding="utf-8")


def test_the_three_assets_exist():
    for name in ("index.html", "app.css", "app.js"):
        assert (WEB / name).is_file(), f"{name} is missing"


def test_html_links_the_split_assets():
    html = _read("index.html")
    assert 'href="app.css"' in html
    assert 'src="app.js"' in html


@pytest.mark.parametrize("element_id", REQUIRED_IDS)
def test_required_element_is_present(element_id):
    assert f'id="{element_id}"' in _read("index.html"), f"#{element_id} is missing"


def test_no_inline_event_handlers():
    html = _read("index.html")
    found = re.findall(r'\son[a-z]+\s*=\s*"', html)
    assert found == [], f"inline handlers found: {found}"


def test_no_file_path_fallback_anywhere():
    # File.path does not exist in WebView2. Reading it and falling back to
    # File.name is the original drag-and-drop bug; paths come from Python.
    js = _read("app.js")
    assert ".path ||" not in js
    assert "dataTransfer.files" not in js


def test_page_declares_a_theme_for_both_schemes():
    css = _read("app.css")
    assert "prefers-color-scheme: dark" in css
    assert ':root[data-theme="dark"]' in css
    assert ':root[data-theme="light"]' in css

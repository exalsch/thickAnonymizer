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
    "review", "review-groups", "review-count", "review-auto", "review-approve-all",
    "review-reject-all", "review-apply", "review-cancel", "review-truncated",
    # report
    "report", "report-headline", "report-types", "report-files", "report-skipped",
    "report-residual", "report-copy", "report-save",
    # confirmation dialog
    "confirm", "confirm-title", "confirm-body", "confirm-yes", "confirm-no",
    # chrome
    "version", "theme-toggle", "banner", "busy", "supported", "output", "choose-output",
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


def test_no_native_blocking_dialogs():
    # window.confirm/alert/prompt block the whole WebView2 renderer, which is
    # indistinguishable from a frozen app if the dialog is not visible.
    js = _read("app.js")
    for banned in ("window.confirm(", "window.alert(", "window.prompt("):
        assert banned not in js, f"{banned} blocks the renderer"


def test_confirm_dialog_exists():
    html = _read("index.html")
    for element_id in ("confirm", "confirm-title", "confirm-body", "confirm-yes", "confirm-no"):
        assert f'id="{element_id}"' in html, f"#{element_id} is missing"


def test_show_modal_is_always_guarded():
    # showModal() on an already-open dialog throws InvalidStateError, which
    # would reject the calling async function and leave a dead-looking app.
    js = _read("app.js")
    assert js.count(".showModal(") == 1, (
        "every showModal call must go through openModal(), which guards dialog.open"
    )
    assert "function openModal(" in js


def test_escape_on_the_review_overlay_is_handled():
    js = _read("app.js")
    assert "addEventListener('cancel'" in js


def test_every_bridge_call_goes_through_the_busy_wrapper():
    # A bridge call made directly would show no indicator, which is the whole
    # point of the wrapper.
    js = _read("app.js")
    direct = [line.strip() for line in js.splitlines() if "api()." in line]
    allowed_markers = ("bridge[method]", "if (!api())", "const bridge = api()")
    offenders = [line for line in direct
                 if not any(marker in line for marker in allowed_markers)]
    assert offenders == [], f"bridge calls bypassing call(): {offenders}"


def test_busy_indicator_respects_reduced_motion():
    css = _read("app.css")
    assert "prefers-reduced-motion" in css


def test_output_field_warns_it_must_be_outside_the_root():
    html = _read("index.html")
    assert 'id="output"' in html
    assert "outside the root folder" in html

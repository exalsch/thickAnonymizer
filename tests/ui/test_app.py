import sys

import pytest

from thickanon.ui.app import close_splash, dropped_paths, webview2_present


def test_dropped_paths_reads_the_pywebview_full_path():
    event = {"dataTransfer": {"files": [
        {"name": "a.txt", "pywebviewFullPath": "C:/data/a.txt"},
        {"name": "b.txt", "pywebviewFullPath": "C:/data/b.txt"},
    ]}}
    assert dropped_paths(event) == ["C:/data/a.txt", "C:/data/b.txt"]


def test_dropped_paths_drops_entries_without_a_real_path():
    # A backend that cannot supply paths must yield nothing, never a bare name.
    event = {"dataTransfer": {"files": [{"name": "a.txt"}, {"name": "b.txt", "pywebviewFullPath": ""}]}}
    assert dropped_paths(event) == []


def test_dropped_paths_tolerates_junk():
    assert dropped_paths(None) == []
    assert dropped_paths({}) == []
    assert dropped_paths({"dataTransfer": {}}) == []
    assert dropped_paths({"dataTransfer": {"files": None}}) == []


@pytest.mark.skipif(sys.platform != "win32", reason="WebView2 is a Windows runtime")
def test_webview2_present_on_this_dev_machine():
    # The dev machine runs the app, so the runtime must be detected. A check
    # that returns False here would block a working machine.
    assert webview2_present() is True


def test_webview2_present_is_true_off_windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    assert webview2_present() is True


def test_close_splash_is_safe_without_pyinstaller():
    close_splash()  # must not raise outside a bundled exe

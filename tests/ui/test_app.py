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


def test_splash_text_is_safe_without_pyinstaller():
    from thickanon.ui.app import splash_text

    splash_text("anything")  # must not raise outside a bundled exe


def test_splash_text_updates_when_pyi_splash_is_present(monkeypatch):
    import sys as _sys
    import types

    calls = []
    fake = types.ModuleType("pyi_splash")
    fake.update_text = lambda message: calls.append(message)
    monkeypatch.setitem(_sys.modules, "pyi_splash", fake)

    from thickanon.ui.app import splash_text

    splash_text("Loading...")
    assert calls == ["Loading..."]


def test_splash_text_survives_a_failing_pyi_splash(monkeypatch):
    import sys as _sys
    import types

    def boom(message):
        raise RuntimeError("splash already closed")

    fake = types.ModuleType("pyi_splash")
    fake.update_text = boom
    monkeypatch.setitem(_sys.modules, "pyi_splash", fake)

    from thickanon.ui.app import splash_text

    splash_text("Loading...")  # a cosmetic message must never break start-up


def test_close_splash_reports_a_failure_instead_of_hiding_it(monkeypatch, capsys):
    import sys as _sys
    import types

    def boom():
        raise RuntimeError("ipc closed")

    fake = types.ModuleType("pyi_splash")
    fake.close = boom
    monkeypatch.setitem(_sys.modules, "pyi_splash", fake)

    from thickanon.ui.app import close_splash

    close_splash()  # must not raise
    assert "could not close the splash screen" in capsys.readouterr().err


def test_close_splash_is_silent_when_not_bundled(monkeypatch, capsys):
    import sys as _sys

    monkeypatch.setitem(_sys.modules, "pyi_splash", None)
    from thickanon.ui.app import close_splash

    close_splash()
    # Outside a bundle there is nothing to close and nothing to say.
    assert capsys.readouterr().err == ""


def test_close_splash_actually_calls_close(monkeypatch):
    import sys as _sys
    import types

    calls = []
    fake = types.ModuleType("pyi_splash")
    fake.close = lambda: calls.append("closed")
    monkeypatch.setitem(_sys.modules, "pyi_splash", fake)

    from thickanon.ui.app import close_splash

    close_splash()
    assert calls == ["closed"]

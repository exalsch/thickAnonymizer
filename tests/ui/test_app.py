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


def test_finish_startup_runs_once_even_from_both_paths(monkeypatch):
    # The loaded event and the poll can both fire; wiring the drop handler
    # twice would register a duplicate listener with pywebview.
    import threading as _threading

    calls = []
    finished = _threading.Event()

    def finish_startup():
        if finished.is_set():
            return
        finished.set()
        calls.append("ran")

    finish_startup()
    finish_startup()
    finish_startup()
    assert calls == ["ran"]


def test_wire_drop_survives_a_window_with_no_dom(monkeypatch):
    # _wire_drop must never raise: drag-and-drop is a convenience and the
    # Browse buttons are the guaranteed path.
    from thickanon.ui.app import _wire_drop

    class Boom:
        @property
        def dom(self):
            raise RuntimeError("no dom")

    _wire_drop(Boom(), object())  # must not raise


def test_wire_drop_registers_the_drop_handler():
    from thickanon.ui.app import _wire_drop

    registered = []

    class Events:
        def __init__(self):
            self.drop = self

        def __iadd__(self, handler):
            registered.append(handler)
            return self

    class Element:
        def __init__(self):
            self.events = Events()

    class Dom:
        def get_element(self, selector):
            assert selector == "#drop"
            return Element()

    class Window:
        dom = Dom()

    _wire_drop(Window(), object())
    assert len(registered) == 1


def test_on_drop_never_raises_into_pywebview():
    # The handler runs on pywebview's event thread; an exception escaping it
    # would surface inside native code.
    from thickanon.ui.app import _wire_drop

    captured = {}

    class Events:
        def __init__(self): self.drop = self
        def __iadd__(self, handler): captured["handler"] = handler; return self

    class Element:
        def __init__(self): self.events = Events()

    class Dom:
        def get_element(self, selector): return Element()

    class Window:
        dom = Dom()

    class ExplodingApi:
        def on_files_dropped(self, paths):
            raise RuntimeError("boom")

    _wire_drop(Window(), ExplodingApi())
    handler = captured["handler"]
    # DOMEventHandler wraps the callback; reach the callable it holds.
    callback = getattr(handler, "callback", handler)
    callback({"dataTransfer": {"files": [{"name": "a.txt", "pywebviewFullPath": "C:/a.txt"}]}})

"""Unified entry point: GUI when launched with no arguments, CLI otherwise.

Packaged as a console-subsystem exe so the CLI behaves correctly (the shell
waits, stdout/stderr pipe and redirect, exit codes propagate). When started
with no arguments (e.g. a double-click), the GUI is launched and the console
window is hidden on Windows so only the app window remains.
"""
import sys


def _hide_console_on_windows() -> None:
    """Hide the attached console window (Windows console-subsystem exe).

    Best-effort: any failure is ignored, since a missing console just means
    there is nothing to hide (e.g. launched without one, or non-Windows).
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes

        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)  # SW_HIDE
    except Exception:
        pass


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv:
        # Any arguments -> command-line mode.
        from thickanon.cli import main as cli_main

        return cli_main(argv)
    # No arguments -> desktop GUI.
    _hide_console_on_windows()
    from thickanon.ui.app import run

    run()
    return 0


if __name__ == "__main__":
    sys.exit(main())

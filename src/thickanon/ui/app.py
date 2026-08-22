"""Desktop window: preflight the renderer, create the window, wire native drops."""
import sys
import threading
import webbrowser
from pathlib import Path

import webview
from webview.dom import DOMEventHandler

from thickanon.ui.api import Api

WEBVIEW2_URL = "https://developer.microsoft.com/microsoft-edge/webview2/"

# Well-known Evergreen WebView2 Runtime client id in the EdgeUpdate registry.
_WEBVIEW2_CLIENT = r"Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"


def webview2_present() -> bool:
    """Is the Edge WebView2 Runtime installed?

    Without it pywebview silently falls back to MSHTML and renders the page
    unusably. A failed check returns True: a false negative must never block a
    machine that would have worked.
    """
    if sys.platform != "win32":
        return True
    try:
        import winreg

        candidates = (
            (winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\WOW6432Node\{_WEBVIEW2_CLIENT}"),
            (winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\{_WEBVIEW2_CLIENT}"),
            (winreg.HKEY_CURRENT_USER, rf"SOFTWARE\{_WEBVIEW2_CLIENT}"),
        )
        for hive, key in candidates:
            try:
                with winreg.OpenKey(hive, key) as handle:
                    version, _ = winreg.QueryValueEx(handle, "pv")
                    if version and version != "0.0.0.0":
                        return True
            except OSError:
                continue
        return False
    except Exception:
        return True


def message_box(title: str, text: str) -> None:
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(None, text, title, 0x10)
            return
        except Exception:
            pass
    print(f"{title}: {text}", file=sys.stderr)


def close_splash() -> None:
    """Dismiss the PyInstaller splash screen. No-op outside a bundled exe.

    A failure here leaves the splash stranded on the user's screen for the
    whole session, so it must never be silent: a swallowed exception here once
    hid exactly that bug. Outside a bundle pyi_splash does not exist, which is
    normal and not worth reporting.
    """
    try:
        import pyi_splash  # provided only inside a PyInstaller bundle
    except ImportError:
        return
    try:
        pyi_splash.close()
    except Exception as exc:
        print(f"warning: could not close the splash screen: {exc}", file=sys.stderr)


def splash_text(message: str) -> None:
    """Update the PyInstaller splash screen's status line.

    No-op outside a bundled exe. During the one-file unpack the bootloader
    overwrites this line with the name of each file it extracts, so these
    messages are what the user sees from the end of the unpack onwards.
    """
    try:
        import pyi_splash  # provided only inside a PyInstaller bundle
    except ImportError:
        return
    try:
        pyi_splash.update_text(message)
    except Exception as exc:
        print(f"warning: could not update the splash screen: {exc}", file=sys.stderr)


def dropped_paths(event) -> list[str]:
    """Pull real filesystem paths out of a pywebview drop event.

    pywebview injects pywebviewFullPath per file on WebView2. Anything without
    one is discarded: a bare File.name is a filename, not a path, and using it
    would resolve against the process working directory.
    """
    files = ((event or {}).get("dataTransfer") or {}).get("files") or []
    return [str(f.get("pywebviewFullPath")) for f in files if f.get("pywebviewFullPath")]


def _wire_drop(window, api: Api) -> None:
    def on_drop(event):
        api.on_files_dropped(dropped_paths(event))

    try:
        element = window.dom.get_element("#drop")
        if element is not None:
            element.events.drop += DOMEventHandler(
                on_drop, prevent_default=True, stop_propagation=True
            )
    except Exception:
        # Drag-and-drop is a convenience; the Browse buttons always work.
        pass


def run() -> int:
    splash_text("Starting thickAnonymizer...")
    if not webview2_present():
        close_splash()
        message_box(
            "thickAnonymizer",
            "Microsoft Edge WebView2 Runtime is required to show the app window.\n\n"
            f"Install the Evergreen Runtime from:\n{WEBVIEW2_URL}\n\n"
            "The command-line mode works without it.",
        )
        webbrowser.open(WEBVIEW2_URL)
        return 1

    html = Path(__file__).parent / "web" / "index.html"
    api = Api()
    splash_text("Opening the window...")
    window = webview.create_window(
        "thickAnonymizer", url=html.as_uri(), js_api=api,
        width=1060, height=840, min_size=(760, 620),
    )
    api.window = window  # let the bridge open dialogs and push progress

    def on_loaded(*_args):
        # Deliberately no splash_text() here. Updating the splash from this
        # thread stopped the subsequent close from working, and a message
        # shown microseconds before the splash is destroyed is worthless.
        _wire_drop(window, api)
        close_splash()

    window.events.loaded += on_loaded
    # Backstop: on_loaded runs on pywebview's event thread, and a failure to
    # close there would strand the splash on screen for the whole session.
    # This timer runs regardless, and closing an already-closed splash is
    # harmless.
    threading.Timer(20.0, close_splash).start()
    webview.start()
    return 0


if __name__ == "__main__":
    sys.exit(run())

import webview
from pathlib import Path
from thickanon.ui.api import Api


def run():
    html = Path(__file__).parent / "web" / "index.html"
    webview.create_window("thickAnonymizer", url=str(html), js_api=Api(),
                          width=900, height=680)
    webview.start()


if __name__ == "__main__":
    run()

import webview
from pathlib import Path
from thickanon.ui.api import Api


def run():
    html = Path(__file__).parent / "web" / "index.html"
    api = Api()
    window = webview.create_window("thickAnonymizer", url=html.as_uri(), js_api=api,
                                   width=900, height=720)
    api.window = window  # let the bridge open native file/folder dialogs
    webview.start()


if __name__ == "__main__":
    run()

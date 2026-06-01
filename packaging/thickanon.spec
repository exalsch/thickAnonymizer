# packaging/thickanon.spec
# Build: pyinstaller packaging/thickanon.spec
from PyInstaller.utils.hooks import collect_all

datas, binaries, hiddenimports = [], [], []
for pkg in ["en_core_web_lg", "presidio_analyzer", "presidio_anonymizer"]:
    d, b, h = collect_all(pkg)
    datas += d; binaries += b; hiddenimports += h

# bundle the web UI
datas += [("src/thickanon/ui/web/index.html", "thickanon/ui/web")]

a = Analysis(["src/thickanon/ui/app.py"], pathex=["src"], datas=datas,
             binaries=binaries, hiddenimports=hiddenimports)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, name="thickAnonymizer",
          console=False)

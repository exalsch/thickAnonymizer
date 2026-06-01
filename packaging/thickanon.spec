# packaging/thickanon.spec
# Build: pyinstaller packaging/thickanon.spec
#
# Produces a single hybrid exe (dist/thickAnonymizer.exe):
#   - double-click / no args  -> desktop GUI (console hidden on launch)
#   - `thickAnonymizer.exe anonymize ...` / `anon ...` etc. -> CLI
# Built as a console-subsystem exe so CLI stdio, piping and exit codes work;
# the GUI path hides the console window (see thickanon/__main__.py).
from PyInstaller.utils.hooks import collect_all, collect_submodules

datas, binaries, hiddenimports = [], [], []
for pkg in ["en_core_web_lg", "presidio_analyzer", "presidio_anonymizer"]:
    d, b, h = collect_all(pkg)
    datas += d; binaries += b; hiddenimports += h

# ensure all of our own modules are bundled (the entry imports them lazily)
hiddenimports += collect_submodules("thickanon")

# bundle the web UI
datas += [("src/thickanon/ui/web/index.html", "thickanon/ui/web")]

a = Analysis(["src/thickanon/__main__.py"], pathex=["src"], datas=datas,
             binaries=binaries, hiddenimports=hiddenimports)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, name="thickAnonymizer",
          console=True)

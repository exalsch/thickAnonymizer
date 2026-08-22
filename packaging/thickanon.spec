# packaging/thickanon.spec
# Build: pyinstaller packaging/thickanon.spec   (or packaging/build.ps1)
#
# Produces a single hybrid exe (dist/thickAnonymizer.exe):
#   - double-click / no args  -> desktop GUI (console hidden on launch)
#   - `thickAnonymizer.exe anonymize ...` / `anon ...` etc. -> CLI
# Built as a console-subsystem exe so CLI stdio, piping and exit codes work;
# the GUI path hides the console window (see thickanon/__main__.py).
import os
from PyInstaller.utils.hooks import collect_all, collect_submodules

# Paths in a .spec are resolved relative to the spec file's directory, so anchor
# everything to the project root (the parent of packaging/) via SPECPATH.
ROOT = os.path.dirname(os.path.abspath(SPECPATH))
SRC = os.path.join(ROOT, "src")
PKG = os.path.join(ROOT, "packaging")

datas, binaries, hiddenimports = [], [], []
for pkg in ["en_core_web_lg", "presidio_analyzer", "presidio_anonymizer"]:
    d, b, h = collect_all(pkg)
    datas += d; binaries += b; hiddenimports += h

# Optional GLiNER backend: bundle the gliner package (and its CPU torch/transformers/
# onnxruntime deps) only if installed. The default build excludes torch/transformers
# (see _EXCLUDES) for a slim CPU-only exe; to ship GLiNER, install the [gliner] extra
# AND remove "torch"/"transformers" from _EXCLUDES before building.
try:
    for _pkg in ("gliner", "onnxruntime"):
        _d, _b, _h = collect_all(_pkg)
        datas += _d; binaries += _b; hiddenimports += _h
except Exception:
    pass

# ensure all of our own modules are bundled (the entry imports them lazily)
hiddenimports += collect_submodules("thickanon")

# bundle the web UI: every asset the page links to must be listed here, or the
# exe ships an unstyled, inert window.
_WEB = os.path.join(SRC, "thickanon", "ui", "web")
datas += [
    (os.path.join(_WEB, "index.html"), "thickanon/ui/web"),
    (os.path.join(_WEB, "app.css"), "thickanon/ui/web"),
    (os.path.join(_WEB, "app.js"), "thickanon/ui/web"),
]

# torch is present in the dev env (so thinc auto-registers it), but the
# en_core_web_lg CNN pipeline runs on thinc/numpy and does not need it for
# inference. Excluding the torch + CUDA stack drops ~2GB; thinc falls back
# cleanly when torch is unimportable.
_EXCLUDES = [
    "torch", "torchvision", "torchaudio", "torchgen", "functorch",
    "nvidia", "triton", "transformers",
]

a = Analysis([os.path.join(SRC, "thickanon/__main__.py")], pathex=[SRC], datas=datas,
             binaries=binaries, hiddenimports=hiddenimports, excludes=_EXCLUDES)
pyz = PYZ(a.pure)

# A one-file exe of this size takes roughly 15 seconds to unpack before any of
# our code runs. Without a splash a double-click looks like nothing happened.
# ui/app.py closes it once the window has loaded.
splash = Splash(
    os.path.join(PKG, "splash.png"),
    binaries=a.binaries,
    datas=a.datas,
    text_pos=(28, 214),
    text_size=10,
    text_color="#97a1b0",
    text_default="Unpacking the application, this takes a few seconds...",
)

# Argument order follows PyInstaller's own --onefile --splash template:
# Analysis' binaries must precede splash's, because normalize_toc() dedups
# first-wins and Analysis' copy should win any filename collision.
exe = EXE(pyz, a.scripts, a.binaries, a.datas, splash, splash.binaries,
          name="thickAnonymizer",
          console=True,
          icon=os.path.join(PKG, "icon.ico"),
          version=os.path.join(PKG, "version_info.txt"))

# packaging/thickanon.spec
# Build: pyinstaller packaging/thickanon.spec
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

datas, binaries, hiddenimports = [], [], []
for pkg in ["en_core_web_lg", "presidio_analyzer", "presidio_anonymizer"]:
    d, b, h = collect_all(pkg)
    datas += d; binaries += b; hiddenimports += h

# Optional GLiNER backend: bundle fast_gliner only if installed. Default build is
# CPU-only; GLiNER mode requires installing the [gliner] extra before building.
try:
    _d, _b, _h = collect_all("fast_gliner")
    datas += _d; binaries += _b; hiddenimports += _h
except Exception:
    pass

# ensure all of our own modules are bundled (the entry imports them lazily)
hiddenimports += collect_submodules("thickanon")

# bundle the web UI
datas += [(os.path.join(SRC, "thickanon/ui/web/index.html"), "thickanon/ui/web")]

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
exe = EXE(pyz, a.scripts, a.binaries, a.datas, name="thickAnonymizer",
          console=True)

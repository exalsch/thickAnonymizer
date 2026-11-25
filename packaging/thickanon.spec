# packaging/thickanon.spec
# Build: pyinstaller packaging/thickanon.spec   (or packaging/build.ps1)
#
# Produces a one-dir app (dist/thickAnonymizer/thickAnonymizer.exe plus its
# _internal folder). One hybrid exe:
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

# GLiNER runs as an ONNX model on onnxruntime + tokenizers (detectors/gliner_onnx.py),
# so neural NER ships in the default exe without PyTorch. The model itself
# (1,16 GB) is downloaded into the Hugging Face cache on first use.
for _pkg in ("onnxruntime", "tokenizers"):
    _d, _b, _h = collect_all(_pkg)
    datas += _d; binaries += _b; hiddenimports += _h

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

# The torch-based gliner package and its PyTorch/CUDA stack are no longer
# dependencies. They stay excluded so a dev venv that still has them cannot
# pull 2 GB into the exe: presidio imports gliner opportunistically.
_EXCLUDES = [
    "torch", "torchvision", "torchaudio", "torchgen", "functorch",
    "nvidia", "triton", "transformers", "gliner",
]

a = Analysis([os.path.join(SRC, "thickanon/__main__.py")], pathex=[SRC], datas=datas,
             binaries=binaries, hiddenimports=hiddenimports, excludes=_EXCLUDES)

# collect_all() adds the Cython and C++ sources of spaCy and its helpers as
# data files: about 70 MB that nothing reads at run time.
_SOURCE_EXTS = (".pyx", ".pxd", ".cpp", ".c", ".h", ".pyi")
a.datas = [d for d in a.datas if not d[0].lower().endswith(_SOURCE_EXTS)]

# PyInstaller finds DLL dependencies through PATH. When another program puts
# its own copy of the Visual C++ runtime on PATH first, that copy is bundled:
# a JDK once put a 2017 msvcp140.dll (14.16) into the app. onnxruntime is built
# with a newer MSVC and crashes with an access violation on a runtime older
# than 14.40, so the runtime is always taken from System32, which the Visual
# C++ Redistributable keeps current. build.ps1 checks the version again.
_SYSTEM32 = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32")
_VC_RUNTIME = (
    "msvcp140.dll", "msvcp140_1.dll", "msvcp140_2.dll",
    "vcruntime140.dll", "vcruntime140_1.dll", "concrt140.dll",
)


def _pin_vc_runtime(binaries):
    pinned = []
    for dest, src, kind in binaries:
        system_copy = os.path.join(_SYSTEM32, os.path.basename(dest))
        if (os.path.dirname(dest) == "" and dest.lower() in _VC_RUNTIME
                and os.path.isfile(system_copy)):
            src = system_copy
        pinned.append((dest, src, kind))
    return pinned


a.binaries = _pin_vc_runtime(a.binaries)

pyz = PYZ(a.pure)

# Loading spaCy and its 400 MB model takes several seconds before any window
# can open. Without a splash a double-click looks like nothing happened.
# ui/app.py closes it once the window has loaded.
# always_on_top defaults to True, which makes the splash float above every
# other window for the whole start-up, so it must be possible to click away.
splash = Splash(
    os.path.join(PKG, "splash.png"),
    binaries=a.binaries,
    datas=a.datas,
    text_pos=(28, 214),
    text_size=10,
    text_color="#97a1b0",
    text_default="Starting the application, this takes a few seconds...",
    always_on_top=False,
)

# One-dir, not one-file. A one-file exe unpacked about 740 MB into %TEMP% on
# every launch, which cost 12 to 19 seconds before any of our code ran
# (docs/reviews/2026-11-23-performance-review.md). The layout follows
# PyInstaller's own one-dir template with a splash: the splash goes into EXE,
# its binaries into COLLECT after Analysis' binaries, because normalize_toc()
# dedups first-wins and Analysis' copy should win any filename collision.
# UPX stays off: it slows DLL loading and trips virus scanners.
exe = EXE(pyz, a.scripts, splash, [],
          exclude_binaries=True,
          name="thickAnonymizer",
          console=True,
          upx=False,
          icon=os.path.join(PKG, "icon.ico"),
          version=os.path.join(PKG, "version_info.txt"))

coll = COLLECT(exe, a.binaries, a.datas, splash.binaries,
               upx=False,
               name="thickAnonymizer")

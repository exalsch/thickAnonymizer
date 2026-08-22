from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "packaging" / "thickanon.spec"


def test_spec_bundles_every_web_asset():
    spec = SPEC.read_text(encoding="utf-8")
    for name in ("index.html", "app.css", "app.js"):
        assert name in spec, f"{name} is not bundled by the PyInstaller spec"


def test_spec_keeps_the_slim_build():
    spec = SPEC.read_text(encoding="utf-8")
    assert '"torch"' in spec and '"transformers"' in spec, "the slim build must keep the excludes"
    assert "console=True" in spec, "the hybrid CLI/GUI exe must stay console-subsystem"


def test_spec_wires_icon_version_and_splash():
    spec = SPEC.read_text(encoding="utf-8")
    assert "icon.ico" in spec
    assert "version_info.txt" in spec
    assert "Splash(" in spec


def test_spec_enables_live_splash_text():
    # text_pos=None disables the splash's status line entirely, which leaves a
    # 488 MB one-file exe looking frozen for its whole unpack.
    spec = SPEC.read_text(encoding="utf-8")
    assert "text_pos=(" in spec, "the splash status line is disabled"
    assert "text_default=" in spec


def test_generated_artifacts_are_committed():
    assert (ROOT / "packaging" / "icon.ico").is_file()
    assert (ROOT / "packaging" / "splash.png").is_file()
    assert (ROOT / "packaging" / "version_info.txt").is_file()


def test_every_web_asset_referenced_by_the_page_exists():
    web = ROOT / "src" / "thickanon" / "ui" / "web"
    html = (web / "index.html").read_text(encoding="utf-8")
    for name in ("app.css", "app.js"):
        assert name in html and (web / name).is_file()


import ast


def _spec_ast():
    return ast.parse(SPEC.read_text(encoding="utf-8"))


def _find_call(tree, func_name):
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == func_name:
            return node
    return None


def test_exe_call_really_receives_the_splash():
    # The substring tests pass if "Splash(" appears anywhere, a comment
    # included. This checks the object is genuinely handed to EXE().
    exe = _find_call(_spec_ast(), "EXE")
    assert exe is not None, "the spec has no EXE(...) call"
    args = [ast.unparse(a) for a in exe.args]
    assert "splash" in args, args
    assert "splash.binaries" in args, args


def test_exe_argument_order_matches_pyinstallers_template():
    # normalize_toc() dedups first-wins, so Analysis' binaries must come first.
    exe = _find_call(_spec_ast(), "EXE")
    args = [ast.unparse(a) for a in exe.args]
    assert args.index("a.binaries") < args.index("splash"), args


def test_excludes_really_lists_torch_and_transformers():
    excludes = None
    for node in ast.walk(_spec_ast()):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "_EXCLUDES" for t in node.targets
        ):
            excludes = {ast.literal_eval(e) for e in node.value.elts}
    assert excludes is not None, "the spec has no _EXCLUDES assignment"
    assert {"torch", "transformers"} <= excludes, excludes


def test_web_assets_are_real_string_literals_in_the_spec():
    literals = {
        n.value for n in ast.walk(_spec_ast())
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
    }
    for name in ("index.html", "app.css", "app.js"):
        assert name in literals, f"{name} is not a string literal in the spec"


def test_splash_does_not_float_above_every_other_window():
    # always_on_top defaults to True. The app takes about 20 seconds to start,
    # so a splash that cannot lose focus blocks the whole desktop meanwhile.
    splash = _find_call(_spec_ast(), "Splash")
    assert splash is not None, "the spec has no Splash(...) call"
    values = {k.arg: k.value for k in splash.keywords}
    assert "always_on_top" in values, "always_on_top is not set, so it defaults to True"
    assert ast.literal_eval(values["always_on_top"]) is False

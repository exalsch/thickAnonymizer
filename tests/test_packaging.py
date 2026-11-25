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
    # included. This checks the object is genuinely handed to EXE() and its
    # binaries to COLLECT(), as in PyInstaller's own one-dir template.
    exe = _find_call(_spec_ast(), "EXE")
    assert exe is not None, "the spec has no EXE(...) call"
    assert "splash" in [ast.unparse(a) for a in exe.args]
    coll = _find_call(_spec_ast(), "COLLECT")
    assert coll is not None, "the spec has no COLLECT(...) call"
    assert "splash.binaries" in [ast.unparse(a) for a in coll.args]


def test_build_is_one_dir_so_nothing_is_unpacked_at_each_start():
    # A one-file exe unpacked about 740 MB into %TEMP% on every launch, which
    # cost 12 to 19 seconds before any of our code ran.
    exe = _find_call(_spec_ast(), "EXE")
    keywords = {k.arg: k.value for k in exe.keywords}
    assert "exclude_binaries" in keywords and ast.literal_eval(keywords["exclude_binaries"]) is True
    exe_args = [ast.unparse(a) for a in exe.args]
    assert "a.binaries" not in exe_args and "a.datas" not in exe_args


def test_collect_argument_order_matches_pyinstallers_template():
    # normalize_toc() dedups first-wins, so Analysis' binaries must come first.
    coll = _find_call(_spec_ast(), "COLLECT")
    args = [ast.unparse(a) for a in coll.args]
    assert args[:3] == ["exe", "a.binaries", "a.datas"], args
    assert args.index("a.binaries") < args.index("splash.binaries"), args


def test_source_files_are_dropped_from_the_bundle():
    # collect_all() adds spaCy's .pyx/.pxd/.cpp sources as data, about 70 MB
    # that nothing reads at run time.
    spec = SPEC.read_text(encoding="utf-8")
    for ext in (".pyx", ".pxd", ".cpp"):
        assert f'"{ext}"' in spec, f"{ext} sources are not filtered out"


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


def test_build_script_does_not_delete_dist_up_front():
    # Removing dist at the start leaves the user with no app for the ten
    # minutes the build takes, and nothing at all if it fails.
    script = (ROOT / "packaging" / "build.ps1").read_text(encoding="utf-8")
    assert "--distpath" in script, "the build must stage the app rather than write straight to dist"
    clean = script.index("Cleaning previous build")
    promote = script.index("Promoting the verified build")
    smoke = script.index("Smoke-testing the exe")
    assert smoke < promote, "the build must be verified before it replaces the previous one"
    assert clean < smoke


def test_build_script_smoke_tests_the_staged_exe():
    script = (ROOT / "packaging" / "build.ps1").read_text(encoding="utf-8")
    # The thing that gets tested must be the thing that was just built.
    assert "$staged" in script
    staged_assign = script.index("$staged = ")
    smoke = script.index("Smoke-testing the exe")
    assert staged_assign < smoke


def test_build_script_keeps_the_previous_app_until_the_new_one_is_in_place():
    # The one-dir app is a folder. It is moved aside, not deleted, so a failed
    # move can put it back.
    script = (ROOT / "packaging" / "build.ps1").read_text(encoding="utf-8")
    assert "$previous" in script
    promote = script.index("Promoting the verified build")
    assert script.index("Rename-Item", promote) < script.index("Remove-Item", script.index("Move-Item", promote))


def test_onnx_runtime_is_collected_outside_any_try():
    # GLiNER runs on onnxruntime + tokenizers. A collect_all inside a
    # try/except once failed on a missing package and silently dropped the
    # runtime from the exe, so these must be collected unconditionally.
    tree = _spec_ast()
    guarded = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Try):
            for inner in ast.walk(node):
                if isinstance(inner, ast.Constant) and isinstance(inner.value, str):
                    guarded.add(inner.value)
    collected = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and ast.unparse(node.func) == "collect_all":
            for arg in node.args:
                if isinstance(arg, ast.Constant):
                    collected.add(arg.value)
        if isinstance(node, ast.For) and isinstance(node.iter, (ast.List, ast.Tuple)):
            if any(isinstance(n, ast.Call) and ast.unparse(n.func) == "collect_all" for n in ast.walk(node)):
                collected |= {e.value for e in node.iter.elts if isinstance(e, ast.Constant)}
    for pkg in ("onnxruntime", "tokenizers"):
        assert pkg in collected, f"{pkg} is not collected"
        assert pkg not in guarded, f"{pkg} is collected inside a try block"


def test_the_torch_based_gliner_package_is_excluded():
    excludes = None
    for node in ast.walk(_spec_ast()):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "_EXCLUDES" for t in node.targets
        ):
            excludes = {ast.literal_eval(e) for e in node.value.elts}
    assert "gliner" in excludes


def test_spec_takes_the_vc_runtime_from_system32():
    # PyInstaller finds DLLs through PATH. A JDK on PATH once put a 2017
    # msvcp140.dll (14.16) into the app and onnxruntime crashed with an access
    # violation on the first GLiNER run, while --help still worked.
    spec = SPEC.read_text(encoding="utf-8")
    assert "System32" in spec
    for name in ("msvcp140.dll", "vcruntime140.dll"):
        assert f'"{name}"' in spec
    assert "a.binaries = _pin_vc_runtime(a.binaries)" in spec
    # it must run before the splash and COLLECT read a.binaries
    assert spec.index("a.binaries = _pin_vc_runtime") < spec.index("splash = Splash(")


def test_build_script_refuses_an_old_vc_runtime():
    script = (ROOT / "packaging" / "build.ps1").read_text(encoding="utf-8")
    assert "msvcp140.dll" in script and "14.40" in script
    # the check must come before the build is promoted
    assert script.index("14.40") < script.index("Promoting the verified build")

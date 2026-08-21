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


def test_generated_artifacts_are_committed():
    assert (ROOT / "packaging" / "icon.ico").is_file()
    assert (ROOT / "packaging" / "splash.png").is_file()
    assert (ROOT / "packaging" / "version_info.txt").is_file()


def test_every_web_asset_referenced_by_the_page_exists():
    web = ROOT / "src" / "thickanon" / "ui" / "web"
    html = (web / "index.html").read_text(encoding="utf-8")
    for name in ("app.css", "app.js"):
        assert name in html and (web / name).is_file()

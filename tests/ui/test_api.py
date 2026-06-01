from pathlib import Path
from thickanon.ui.api import Api, infer_root, default_mapping_for_root


def test_api_anonymize_reports_summary(tmp_path):
    root = tmp_path / "data"; root.mkdir()
    f = root / "n.txt"; f.write_text("call 10.0.0.3", encoding="utf-8")
    api = Api()
    result = api.anonymize(
        files=[str(f)], root=str(root), mapping_path=str(tmp_path / "m.json"),
        mode="auto_redact", deny=[], backup_dir=None, passphrase=None,
    )
    assert result["ok"] is True
    assert "IP" in result["summary"]
    assert "10.0.0.3" not in f.read_text(encoding="utf-8")


def test_api_anonymize_then_deanonymize_roundtrip(tmp_path):
    root = tmp_path / "data"; root.mkdir()
    f = root / "n.txt"; f.write_text("call 10.0.0.3", encoding="utf-8")
    mp = str(tmp_path / "m.json")  # outside root
    api = Api()
    api.anonymize(files=[str(f)], root=str(root), mapping_path=mp,
                  mode="auto_redact", deny=[], backup_dir=None, passphrase=None)

    result = api.deanonymize(files=[str(f)], mapping_path=mp, passphrase=None)
    assert result["ok"] is True
    assert f.read_text(encoding="utf-8") == "call 10.0.0.3"


def test_api_rejects_mapping_inside_root(tmp_path):
    root = tmp_path / "data"; root.mkdir()
    f = root / "n.txt"; f.write_text("call 10.0.0.3", encoding="utf-8")
    api = Api()
    result = api.anonymize(
        files=[str(f)], root=str(root), mapping_path=str(root / "m.json"),
        mode="auto_redact", deny=[], backup_dir=None, passphrase=None,
    )
    assert result["ok"] is False
    assert "outside the root" in result["error"]
    assert f.read_text(encoding="utf-8") == "call 10.0.0.3"  # not anonymized


def test_api_returns_error_dict_on_failure(tmp_path):
    # Loading a non-existent mapping must surface as ok:False, not raise.
    api = Api()
    result = api.deanonymize(files=[], mapping_path=str(tmp_path / "missing.json"),
                             passphrase=None)
    assert result["ok"] is False
    assert "error" in result


def test_infer_root_single_dir_and_common_parent(tmp_path):
    root = tmp_path / "data"; (root / "a").mkdir(parents=True); (root / "b").mkdir()
    f1 = root / "a" / "x.txt"; f1.write_text("x", encoding="utf-8")
    f2 = root / "b" / "y.txt"; f2.write_text("y", encoding="utf-8")
    # a single directory is its own root
    assert infer_root([str(root)]) == root
    # multiple files -> common parent
    assert infer_root([str(f1), str(f2)]) == root
    # empty selection -> None
    assert infer_root([]) is None


def test_default_mapping_is_outside_root(tmp_path):
    root = tmp_path / "data"; root.mkdir()
    mp = default_mapping_for_root(root)
    assert mp.parent == tmp_path           # beside root, not inside
    assert root not in mp.parents and mp.parent != root


def test_suggest_defaults_infers_root_and_mapping(tmp_path):
    root = tmp_path / "data"; root.mkdir()
    f = root / "n.txt"; f.write_text("hi", encoding="utf-8")
    api = Api()
    res = api.suggest_defaults([str(f)], root="")
    assert res["ok"] and Path(res["root"]).resolve() == root.resolve()
    # suggested mapping must be outside the inferred root
    assert Path(res["mapping"]).resolve().parent != root.resolve()


def test_suggest_defaults_empty_when_no_common_root(tmp_path):
    # infer_root returns None for an empty selection -> no defaults, no crash.
    api = Api()
    res = api.suggest_defaults([], root="")
    assert res["ok"] and res["root"] == "" and res["mapping"] == ""


def test_anonymize_with_blank_root_infers_and_succeeds(tmp_path):
    # Reproduces the drag-and-drop bug: no root set, no mapping set.
    root = tmp_path / "data"; root.mkdir()
    f = root / "n.txt"; f.write_text("call 10.0.0.3", encoding="utf-8")
    api = Api()
    result = api.anonymize(
        files=[str(f)], root="", mapping_path="",
        mode="auto_redact", deny=[], backup_dir=None, passphrase=None,
    )
    assert result["ok"] is True, result
    assert "10.0.0.3" not in f.read_text(encoding="utf-8")
    # mapping was auto-placed outside root and actually written
    assert Path(result["mapping_path"]).exists()
    assert Path(result["mapping_path"]).parent != root

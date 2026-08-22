import json
from pathlib import Path

from thickanon.ui.api import (
    Api,
    default_backup_for_root,
    default_mapping_for_root,
    gliner_availability,
    infer_root,
    settings_path,
)


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


def _root_with_file(tmp_path, text="mail jane@acme.com and ping 10.0.0.3"):
    root = tmp_path / "data"
    root.mkdir()
    f = root / "n.txt"
    f.write_text(text, encoding="utf-8")
    return root, f


def test_environment_reports_version_and_gliner(tmp_path):
    env = Api().environment()
    assert env["ok"] is True
    assert env["version"]
    assert set(env["gliner"]) == {"available", "reason"}
    if not env["gliner"]["available"]:
        assert "pip install" not in env["gliner"]["reason"].lower()


def test_gliner_availability_reason_is_end_user_language():
    available, reason = gliner_availability()
    assert isinstance(available, bool)
    if not available:
        assert reason and "pip" not in reason.lower()


def test_scan_previews_without_writing(tmp_path):
    root, f = _root_with_file(tmp_path)
    before = f.read_text(encoding="utf-8")
    api = Api()

    result = api.scan({"files": [str(f)], "root": str(root), "mode": "auto_redact"})

    assert result["ok"] is True
    assert f.read_text(encoding="utf-8") == before
    assert result["counts"]["auto"] >= 2
    assert result["scan_id"]
    json.dumps(result)  # the whole payload must cross the JS bridge


def test_scan_then_apply_writes_and_saves_the_mapping(tmp_path):
    root, f = _root_with_file(tmp_path)
    api = Api()
    scan = api.scan({"files": [str(f)], "root": str(root), "mode": "auto_redact"})
    applied = api.apply(scan["scan_id"], [], {
        "mapping": str(tmp_path / "m.json"),
        "backup_enabled": False,
    })

    assert applied["ok"] is True, applied
    out = f.read_text(encoding="utf-8")
    assert "10.0.0.3" not in out and "jane@acme.com" not in out
    assert Path(applied["mapping_path"]).exists()
    assert "IP" in applied["summary"]


def test_apply_applies_only_approved_review_candidates(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    f = root / "n.txt"
    f.write_text("see intranet.example.com for details", encoding="utf-8")
    api = Api()

    scan = api.scan({"files": [str(f)], "root": str(root), "mode": "quick_review"})
    assert scan["review"], "the fixture must produce a review-band candidate"

    api.apply(scan["scan_id"], [], {"mapping": str(tmp_path / "m1.json"),
                                    "backup_enabled": False})
    assert "intranet.example.com" in f.read_text(encoding="utf-8")

    scan = api.scan({"files": [str(f)], "root": str(root), "mode": "quick_review"})
    ids = [c["id"] for c in scan["review"]]
    api.apply(scan["scan_id"], ids, {"mapping": str(tmp_path / "m2.json"),
                                     "backup_enabled": False})
    assert "intranet.example.com" not in f.read_text(encoding="utf-8")


def test_apply_approve_all_covers_a_truncated_review_list(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    f = root / "n.txt"
    f.write_text("see intranet.example.com for details", encoding="utf-8")
    api = Api()
    scan = api.scan({"files": [str(f)], "root": str(root), "mode": "quick_review"})

    api.apply(scan["scan_id"], [], {"mapping": str(tmp_path / "m.json"),
                                    "backup_enabled": False, "approve_all": True})
    assert "intranet.example.com" not in f.read_text(encoding="utf-8")


def test_apply_with_a_stale_scan_id_is_refused(tmp_path):
    root, f = _root_with_file(tmp_path)
    api = Api()
    api.scan({"files": [str(f)], "root": str(root), "mode": "auto_redact"})
    result = api.apply("not-a-real-scan", [], {"mapping": str(tmp_path / "m.json")})
    assert result["ok"] is False
    assert "scan again" in result["error"].lower()
    assert "10.0.0.3" in f.read_text(encoding="utf-8")


def test_apply_rejects_mapping_inside_root(tmp_path):
    root, f = _root_with_file(tmp_path)
    api = Api()
    scan = api.scan({"files": [str(f)], "root": str(root), "mode": "auto_redact"})
    result = api.apply(scan["scan_id"], [], {"mapping": str(root / "m.json"),
                                             "backup_enabled": False})
    assert result["ok"] is False
    assert "outside the root" in result["error"]
    assert "10.0.0.3" in f.read_text(encoding="utf-8")


def test_apply_rejects_backup_inside_root(tmp_path):
    root, f = _root_with_file(tmp_path)
    api = Api()
    scan = api.scan({"files": [str(f)], "root": str(root), "mode": "auto_redact"})
    result = api.apply(scan["scan_id"], [], {
        "mapping": str(tmp_path / "m.json"),
        "backup_enabled": True,
        "backup": str(root / ".backup"),
    })
    assert result["ok"] is False
    assert "outside the root" in result["error"]
    assert "10.0.0.3" in f.read_text(encoding="utf-8")
    assert not (root / ".backup").exists()


def test_apply_refuses_an_unwritable_mapping_before_touching_any_file(tmp_path):
    # The mapping is the only key. Discovering it cannot be saved after every
    # file has been overwritten is unrecoverable when backups are off.
    root, f = _root_with_file(tmp_path)
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")
    api = Api()
    scan = api.scan({"files": [str(f)], "root": str(root), "mode": "auto_redact"})
    result = api.apply(scan["scan_id"], [], {
        "mapping": str(blocker / "sub" / "m.json"),
        "backup_enabled": False,
    })

    assert result["ok"] is False
    assert "mapping file cannot be written" in result["error"]
    assert "10.0.0.3" in f.read_text(encoding="utf-8")


def test_apply_backs_up_by_default(tmp_path):
    root, f = _root_with_file(tmp_path)
    api = Api()
    scan = api.scan({"files": [str(f)], "root": str(root), "mode": "auto_redact"})
    result = api.apply(scan["scan_id"], [], {"mapping": str(tmp_path / "m.json")})

    assert result["ok"] is True, result
    backup = Path(result["backup_root"])
    assert backup == default_backup_for_root(root)
    assert (backup / "n.txt").read_text(encoding="utf-8").count("10.0.0.3") == 1


def test_default_backup_is_outside_root(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    backup = default_backup_for_root(root)
    assert backup.parent == tmp_path
    assert root not in backup.parents and backup != root


def test_roundtrip_through_the_api(tmp_path):
    root, f = _root_with_file(tmp_path, "ping 10.0.0.3")
    mapping_path = str(tmp_path / "m.json")
    api = Api()
    scan = api.scan({"files": [str(f)], "root": str(root), "mode": "auto_redact"})
    api.apply(scan["scan_id"], [], {"mapping": mapping_path, "backup_enabled": False})

    result = api.deanonymize({"files": [str(f)], "mapping": mapping_path})
    assert result["ok"] is True
    assert f.read_text(encoding="utf-8") == "ping 10.0.0.3"
    assert result["report"]["total_restored"] == 1


def test_deanonymize_without_a_mapping_is_refused(tmp_path):
    api = Api()
    result = api.deanonymize({"files": ["x.txt"], "mapping": ""})
    assert result["ok"] is False
    assert "mapping" in result["error"].lower()


def test_errors_come_back_as_dicts_not_exceptions(tmp_path):
    api = Api()
    result = api.deanonymize({"files": ["x.txt"], "mapping": str(tmp_path / "missing.json")})
    assert result["ok"] is False
    assert "error" in result


def test_scan_requires_files():
    result = Api().scan({"files": []})
    assert result["ok"] is False
    assert "no files" in result["error"].lower()


def test_settings_roundtrip_never_stores_the_passphrase(tmp_path, monkeypatch):
    monkeypatch.setenv("THICKANON_CONFIG_DIR", str(tmp_path))
    api = Api()
    api.save_settings({"mode": "auto_redact", "deny": "acme", "backup_enabled": False,
                       "passphrase": "hunter2", "unknown_key": "dropped"})

    raw = settings_path().read_text(encoding="utf-8")
    assert "hunter2" not in raw
    assert "unknown_key" not in raw

    loaded = Api().load_settings()
    assert loaded["ok"] is True
    assert loaded["settings"]["mode"] == "auto_redact"
    assert loaded["settings"]["deny"] == "acme"
    assert "passphrase" not in loaded["settings"]


def test_load_settings_survives_a_corrupt_file(tmp_path, monkeypatch):
    monkeypatch.setenv("THICKANON_CONFIG_DIR", str(tmp_path))
    settings_path().parent.mkdir(parents=True, exist_ok=True)
    settings_path().write_text("{not json", encoding="utf-8")
    result = Api().load_settings()
    assert result["ok"] is True
    assert result["settings"] == {}


def test_suggest_defaults_includes_a_backup_path(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    f = root / "n.txt"
    f.write_text("hi", encoding="utf-8")
    res = Api().suggest_defaults([str(f)], root="")
    assert Path(res["backup"]).resolve() == default_backup_for_root(root)


def test_save_report_needs_a_window():
    result = Api().save_report({"totals": {}}, "r.json")
    assert result["ok"] is False


def test_save_report_writes_json(tmp_path):
    class FakeWindow:
        def create_file_dialog(self, *_args, **_kwargs):
            return (str(tmp_path / "r.json"),)

    api = Api()
    api.window = FakeWindow()
    result = api.save_report({"totals": {"IP": 2}}, "r.json")
    assert result["ok"] is True
    assert json.loads(Path(result["path"]).read_text(encoding="utf-8")) == {"totals": {"IP": 2}}


def test_on_files_dropped_records_paths():
    api = Api()
    result = api.on_files_dropped(["C:/a.txt", "", None, "C:/b.txt"])
    assert result["ok"] is True
    assert result["paths"] == ["C:/a.txt", "C:/b.txt"]


def test_gliner_threshold_of_zero_survives(tmp_path):
    root, f = _root_with_file(tmp_path)
    api = Api()
    cfg = api._config_from({"mode": "auto_redact", "gliner": True, "gliner_threshold": 0})
    assert cfg.gliner is not None
    assert cfg.gliner.threshold == 0


def test_apply_refuses_a_mapping_path_that_is_a_folder(tmp_path):
    root, f = _root_with_file(tmp_path)
    folder = tmp_path / "not-a-file"
    folder.mkdir()
    api = Api()
    scan = api.scan({"files": [str(f)], "root": str(root), "mode": "auto_redact"})
    result = api.apply(scan["scan_id"], [], {"mapping": str(folder),
                                             "backup_enabled": False})

    assert result["ok"] is False
    assert "is a folder" in result["error"]
    assert "10.0.0.3" in f.read_text(encoding="utf-8")


def test_apply_rescues_the_mapping_when_the_chosen_path_fails(tmp_path, monkeypatch):
    # Once the files are rewritten the mapping is the only way back, so a save
    # failure must produce a rescue copy and a loud warning, never a lost key.
    import thickanon.ui.api as api_module
    from thickanon.core.mapping import MappingStore as RealStore

    root, f = _root_with_file(tmp_path)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(api_module.Path, "home", staticmethod(lambda: home))

    real_save = RealStore.save
    calls = {"n": 0}

    def flaky_save(self, path, passphrase=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("device disappeared")
        return real_save(self, path, passphrase=passphrase)

    monkeypatch.setattr(RealStore, "save", flaky_save)

    api = Api()
    scan = api.scan({"files": [str(f)], "root": str(root), "mode": "auto_redact"})
    result = api.apply(scan["scan_id"], [], {"mapping": str(tmp_path / "m.json"),
                                             "backup_enabled": False})

    assert result["ok"] is True, result
    rescued = list(home.glob("thickanon-RESCUE-mapping-*.json"))
    assert len(rescued) == 1
    assert result["mapping_path"] == str(rescued[0])
    assert "only way to reverse" in result["warning"]
    # and the rescued mapping really does reverse the run
    restored = api.deanonymize({"files": [str(f)], "mapping": result["mapping_path"]})
    assert restored["ok"] is True
    assert "10.0.0.3" in f.read_text(encoding="utf-8")


def test_apply_reports_no_warning_on_the_happy_path(tmp_path):
    root, f = _root_with_file(tmp_path)
    api = Api()
    scan = api.scan({"files": [str(f)], "root": str(root), "mode": "auto_redact"})
    result = api.apply(scan["scan_id"], [], {"mapping": str(tmp_path / "m.json"),
                                             "backup_enabled": False})
    assert result["ok"] is True
    assert result["warning"] == ""


def test_a_rejected_backup_leaves_no_stray_mapping_directories(tmp_path):
    root, f = _root_with_file(tmp_path)
    api = Api()
    scan = api.scan({"files": [str(f)], "root": str(root), "mode": "auto_redact"})
    result = api.apply(scan["scan_id"], [], {
        "mapping": str(tmp_path / "keys" / "deep" / "m.json"),
        "backup_enabled": True,
        "backup": str(root / ".backup"),
    })

    assert result["ok"] is False
    assert "outside the root" in result["error"]
    assert not (tmp_path / "keys").exists()


def test_second_run_continues_the_existing_mapping(tmp_path):
    # Replacing the mapping would strand run 1's tokens: counters restart at 1,
    # so run 2's [EMAIL_1] would be a different person and de-anonymizing run
    # 1's files would silently restore the wrong values.
    root = tmp_path / "data"
    root.mkdir()
    a = root / "a.txt"
    a.write_text("mail jane@acme.com", encoding="utf-8")
    mapping_path = str(tmp_path / "m.json")
    api = Api()

    scan = api.scan({"files": [str(a)], "root": str(root), "mode": "auto_redact"})
    api.apply(scan["scan_id"], [], {"mapping": mapping_path, "backup_enabled": False})
    first = a.read_text(encoding="utf-8")

    b = root / "b.txt"
    b.write_text("mail bob@evil.com", encoding="utf-8")
    scan = api.scan({"files": [str(b)], "root": str(root), "mode": "auto_redact"})
    result = api.apply(scan["scan_id"], [], {"mapping": mapping_path,
                                             "backup_enabled": False})
    assert result["ok"] is True, result

    # run 1's token must still resolve to run 1's value
    restored = api.deanonymize({"files": [str(a)], "mapping": mapping_path})
    assert restored["ok"] is True
    assert a.read_text(encoding="utf-8") == "mail jane@acme.com"
    # and run 2 must have been given a DIFFERENT token
    assert b.read_text(encoding="utf-8") != first


def test_a_second_run_does_not_clobber_the_first_backup(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    a = root / "a.txt"
    a.write_text("mail jane@acme.com", encoding="utf-8")
    backup = tmp_path / "bk"
    api = Api()

    scan = api.scan({"files": [str(a)], "root": str(root), "mode": "auto_redact"})
    api.apply(scan["scan_id"], [], {"mapping": str(tmp_path / "m.json"),
                                    "backup_enabled": True, "backup": str(backup)})
    assert (backup / "a.txt").read_text(encoding="utf-8") == "mail jane@acme.com"

    scan = api.scan({"files": [str(a)], "root": str(root), "mode": "auto_redact"})
    api.apply(scan["scan_id"], [], {"mapping": str(tmp_path / "m.json"),
                                    "backup_enabled": True, "backup": str(backup)})
    # the pristine original must survive the second run
    assert (backup / "a.txt").read_text(encoding="utf-8") == "mail jane@acme.com"


def test_wrong_passphrase_on_an_existing_mapping_refuses_before_writing(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    a = root / "a.txt"
    a.write_text("mail jane@acme.com", encoding="utf-8")
    mapping_path = str(tmp_path / "m.json")
    api = Api()

    scan = api.scan({"files": [str(a)], "root": str(root), "mode": "auto_redact"})
    api.apply(scan["scan_id"], [], {"mapping": mapping_path, "backup_enabled": False,
                                    "passphrase": "right"})
    after_first = a.read_text(encoding="utf-8")

    a.write_text("mail bob@evil.com", encoding="utf-8")
    scan = api.scan({"files": [str(a)], "root": str(root), "mode": "auto_redact"})
    result = api.apply(scan["scan_id"], [], {"mapping": mapping_path,
                                             "backup_enabled": False,
                                             "passphrase": "wrong"})
    assert result["ok"] is False
    assert "already exists" in result["error"]
    assert a.read_text(encoding="utf-8") == "mail bob@evil.com"  # untouched
    assert after_first  # first run's output was not disturbed


def test_an_unknown_review_mode_gives_a_readable_error(tmp_path):
    root, f = _root_with_file(tmp_path)
    result = Api().scan({"files": [str(f)], "root": str(root), "mode": "x"})
    assert result["ok"] is False
    assert "unknown review mode" in result["error"]

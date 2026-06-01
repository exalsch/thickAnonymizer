from thickanon.ui.api import Api


def test_api_anonymize_reports_summary(tmp_path):
    f = tmp_path / "n.txt"; f.write_text("call 10.0.0.3", encoding="utf-8")
    api = Api()
    result = api.anonymize(
        files=[str(f)], root=str(tmp_path), mapping_path=str(tmp_path / "m.json"),
        mode="auto_redact", deny=[], backup_dir=None, passphrase=None,
    )
    assert result["ok"] is True
    assert "IP" in result["summary"]
    assert "10.0.0.3" not in f.read_text(encoding="utf-8")


def test_api_anonymize_then_deanonymize_roundtrip(tmp_path):
    f = tmp_path / "n.txt"; f.write_text("call 10.0.0.3", encoding="utf-8")
    mp = str(tmp_path / "m.json")
    api = Api()
    api.anonymize(files=[str(f)], root=str(tmp_path), mapping_path=mp,
                  mode="auto_redact", deny=[], backup_dir=None, passphrase=None)

    result = api.deanonymize(files=[str(f)], mapping_path=mp, passphrase=None)
    assert result["ok"] is True
    assert f.read_text(encoding="utf-8") == "call 10.0.0.3"


def test_api_returns_error_dict_on_failure(tmp_path):
    # Loading a non-existent mapping must surface as ok:False, not raise.
    api = Api()
    result = api.deanonymize(files=[], mapping_path=str(tmp_path / "missing.json"),
                             passphrase=None)
    assert result["ok"] is False
    assert "error" in result

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

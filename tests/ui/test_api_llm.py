from thickanon.ui.api import Api
from thickanon.detectors import llm_model


def test_api_anonymize_with_llm(tmp_path, monkeypatch):
    monkeypatch.setattr(llm_model, "load_runner",
                        lambda cfg: (lambda prompt: '[{"type":"PERSON","text":"John Carter"}]'))
    root = tmp_path / "data"; root.mkdir()
    f = root / "n.txt"; f.write_text("John Carter at 10.0.0.3", encoding="utf-8")
    api = Api()
    res = api.anonymize(files=[str(f)], root=str(root), mapping_path=str(tmp_path / "m.json"),
                        mode="auto_redact", deny=[], backup_dir=None, passphrase=None,
                        llm=True, llm_instruction="thorough", llm_gpu_layers=0)
    assert res["ok"] is True
    assert "John Carter" not in f.read_text(encoding="utf-8")


def test_api_download_model(monkeypatch):
    monkeypatch.setattr(llm_model, "ensure_model", lambda cfg: "/fake/m.gguf")
    res = Api().download_model()
    assert res["ok"] is True and res["path"] == "/fake/m.gguf"

from thickanon.ui.api import Api
from thickanon.detectors import gliner_model


class StubModel:
    def predict_entities(self, text, labels, threshold=0.5):
        i = text.find("John Carter")
        return ([{"label": "person", "text": "John Carter",
                  "start": i, "end": i + 11, "score": 0.9}] if i != -1 else [])


def test_api_anonymize_with_gliner(tmp_path, monkeypatch):
    monkeypatch.setattr(gliner_model, "load_model", lambda cfg: StubModel())
    root = tmp_path / "data"; root.mkdir()
    f = root / "n.txt"; f.write_text("John Carter at 10.0.0.3", encoding="utf-8")
    res = Api().anonymize(files=[str(f)], root=str(root),
                          mapping_path=str(tmp_path / "m.json"), mode="auto_redact",
                          deny=[], backup_dir=None, passphrase=None,
                          gliner=True, gliner_labels="person,location",
                          gliner_threshold=0.4, gliner_gpu=False)
    assert res["ok"] is True
    assert "John Carter" not in f.read_text(encoding="utf-8")


def test_api_download_model(monkeypatch):
    monkeypatch.setattr(gliner_model, "load_model", lambda cfg: object())
    res = Api().download_model()
    assert res["ok"] is True

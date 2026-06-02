from thickanon.cli import main
from thickanon.detectors import gliner_model

class StubModel:
    def predict_entities(self, text, labels, threshold=0.5):
        i = text.find("John Carter")
        return ([{"label": "person", "text": "John Carter",
                  "start": i, "end": i + 11, "score": 0.9}] if i != -1 else [])

def test_cli_gliner_flag_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(gliner_model, "load_model", lambda cfg: StubModel())
    root = tmp_path / "data"; root.mkdir()
    f = root / "x.txt"; f.write_text("John Carter pinged 10.0.0.7", encoding="utf-8")
    mp = tmp_path / "map.json"
    rc = main(["anon", str(f), "--root", str(root), "--mapping", str(mp),
               "--mode", "auto_redact", "--gliner",
               "--gliner-labels", "person,location", "--gliner-threshold", "0.4"])
    assert rc == 0
    out = f.read_text(encoding="utf-8")
    assert "John Carter" not in out and "10.0.0.7" not in out

def test_cli_download_model(tmp_path, monkeypatch, capsys):
    called = {}
    monkeypatch.setattr(gliner_model, "load_model",
                        lambda cfg: called.setdefault("m", object()))
    rc = main(["download-model"])
    assert rc == 0 and "m" in called
    assert "ready" in capsys.readouterr().out.lower()

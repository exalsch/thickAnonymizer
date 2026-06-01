from thickanon.cli import main
from thickanon.detectors import llm_model


def test_cli_llm_flag_runs_with_stub(tmp_path, monkeypatch):
    monkeypatch.setattr(llm_model, "load_runner",
                        lambda cfg: (lambda prompt: '[{"type":"PERSON","text":"John Carter"}]'))
    root = tmp_path / "data"; root.mkdir()
    f = root / "x.txt"; f.write_text("John Carter pinged 10.0.0.7", encoding="utf-8")
    mp = tmp_path / "map.json"
    rc = main(["anon", str(f), "--root", str(root), "--mapping", str(mp),
               "--mode", "auto_redact", "--llm", "--llm-instruction", "be thorough"])
    assert rc == 0
    out = f.read_text(encoding="utf-8")
    assert "John Carter" not in out and "10.0.0.7" not in out


def test_cli_download_model_invokes_ensure(tmp_path, monkeypatch, capsys):
    called = {}
    monkeypatch.setattr(llm_model, "ensure_model",
                        lambda cfg: called.setdefault("path", "/fake/m.gguf") or "/fake/m.gguf")
    rc = main(["download-model"])
    assert rc == 0 and called["path"] == "/fake/m.gguf"
    assert "/fake/m.gguf" in capsys.readouterr().out

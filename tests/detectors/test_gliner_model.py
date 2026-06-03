import builtins, pytest
from thickanon.core.types import GLiNERConfig
from thickanon.detectors import gliner_model


def test_load_model_raises_clear_error_without_gliner(monkeypatch):
    real_import = builtins.__import__
    def fake_import(name, *a, **k):
        if name == "gliner" or name.startswith("gliner."):
            raise ImportError("no gliner")
        return real_import(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(RuntimeError) as exc:
        gliner_model.load_model(GLiNERConfig(model_id="x"))
    assert "gliner" in str(exc.value)


def test_load_model_is_cached_per_config(monkeypatch):
    monkeypatch.setattr(gliner_model, "_model_cache", {})
    calls = []
    monkeypatch.setattr(gliner_model, "_build_model",
                        lambda cfg: calls.append(1) or object())
    m1 = gliner_model.load_model(GLiNERConfig(model_id="a"))
    m2 = gliner_model.load_model(GLiNERConfig(model_id="a"))   # same key
    m3 = gliner_model.load_model(GLiNERConfig(model_id="b"))   # different key
    assert m1 is m2 and len(calls) == 2

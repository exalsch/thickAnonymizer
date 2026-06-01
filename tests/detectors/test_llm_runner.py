import builtins, pytest
from thickanon.core.types import LLMConfig
from thickanon.detectors import llm_model

def test_load_runner_raises_clear_error_without_llama_cpp(tmp_path, monkeypatch):
    # make a fake model file so ensure_model returns immediately
    m = tmp_path / "m.gguf"; m.write_bytes(b"x")
    cfg = LLMConfig(model_path=str(m), sha256="")
    real_import = builtins.__import__
    def fake_import(name, *a, **k):
        if name == "llama_cpp" or name.startswith("llama_cpp."):
            raise ImportError("no llama_cpp")
        return real_import(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(RuntimeError) as exc:
        llm_model.load_runner(cfg)
    assert "llama-cpp-python" in str(exc.value)

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


def test_load_runner_is_cached_per_config(monkeypatch):
    from thickanon.core.types import LLMConfig
    monkeypatch.setattr(llm_model, "_runner_cache", {})  # isolate cache
    calls = []
    monkeypatch.setattr(llm_model, "_build_runner",
                        lambda cfg: calls.append(1) or (lambda prompt: "[]"))
    r1 = llm_model.load_runner(LLMConfig(model_path="/m.gguf", n_gpu_layers=0))
    r2 = llm_model.load_runner(LLMConfig(model_path="/m.gguf", n_gpu_layers=0))  # same key
    r3 = llm_model.load_runner(LLMConfig(model_path="/other.gguf"))             # different key
    assert r1 is r2            # same runner reused
    assert len(calls) == 2     # built once for /m.gguf, once for /other.gguf

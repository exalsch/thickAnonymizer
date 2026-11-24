import builtins

import pytest

from thickanon.core.types import DEFAULT_GLINER_LABELS, DEFAULT_GLINER_MODEL_ID, GLiNERConfig
from thickanon.detectors import gliner_model


def test_load_model_raises_clear_error_without_onnxruntime(monkeypatch):
    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if name == "onnxruntime" or name.startswith("onnxruntime."):
            raise ImportError("no onnxruntime")
        return real_import(name, *a, **k)

    monkeypatch.setattr(gliner_model, "_model_cache", {})
    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(RuntimeError) as exc:
        gliner_model.load_model(GLiNERConfig(model_path="x"))
    assert "onnxruntime" in str(exc.value)


def test_load_model_is_cached_per_config(monkeypatch):
    monkeypatch.setattr(gliner_model, "_model_cache", {})
    calls = []
    monkeypatch.setattr(gliner_model, "_build_model",
                        lambda cfg: calls.append(1) or object())
    m1 = gliner_model.load_model(GLiNERConfig(model_id="a"))
    m2 = gliner_model.load_model(GLiNERConfig(model_id="a"))   # same key
    m3 = gliner_model.load_model(GLiNERConfig(model_id="b"))   # different key
    assert m1 is m2 and m3 is not m1 and len(calls) == 2


def test_a_model_folder_without_the_onnx_file_is_refused(tmp_path):
    (tmp_path / "gliner_config.json").write_text("{}", encoding="utf-8")
    (tmp_path / "tokenizer.json").write_text("{}", encoding="utf-8")
    with pytest.raises(RuntimeError) as exc:
        gliner_model.resolve_model_dir(GLiNERConfig(model_path=str(tmp_path)))
    assert "onnx/model.onnx" in str(exc.value)


def test_the_hub_model_is_taken_from_the_cache_before_the_network(monkeypatch, tmp_path):
    calls = []

    def fake_snapshot(repo_id, revision, allow_patterns, local_files_only=False):
        calls.append(local_files_only)
        for name in allow_patterns:
            (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
            (tmp_path / name).write_text("x", encoding="utf-8")
        return str(tmp_path)

    monkeypatch.setattr(gliner_model, "_snapshot_download", fake_snapshot)
    assert gliner_model.resolve_model_dir(GLiNERConfig()) == tmp_path
    assert calls == [True]


def test_the_hub_model_is_downloaded_when_it_is_not_cached(monkeypatch, tmp_path):
    calls = []

    def fake_snapshot(repo_id, revision, allow_patterns, local_files_only=False):
        calls.append((repo_id, revision, local_files_only))
        if local_files_only:
            raise FileNotFoundError("not cached")
        for name in allow_patterns:
            (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
            (tmp_path / name).write_text("x", encoding="utf-8")
        return str(tmp_path)

    monkeypatch.setattr(gliner_model, "_snapshot_download", fake_snapshot)
    gliner_model.resolve_model_dir(GLiNERConfig())
    assert [c[2] for c in calls] == [True, False]
    # the default model is pinned to one revision, so it cannot change silently
    assert calls[1][0] == DEFAULT_GLINER_MODEL_ID and len(calls[1][1]) == 40


def test_gpu_without_a_gpu_provider_is_a_clear_error(monkeypatch):
    import onnxruntime
    monkeypatch.setattr(onnxruntime, "get_available_providers", lambda: ["CPUExecutionProvider"])
    with pytest.raises(RuntimeError) as exc:
        gliner_model.providers_for(GLiNERConfig(gpu=True))
    assert "GPU" in str(exc.value)


def test_cpu_uses_the_cpu_provider():
    assert gliner_model.providers_for(GLiNERConfig()) == ["CPUExecutionProvider"]


def test_default_labels_cover_technical_identifiers():
    for label in ("hostname", "username", "ip address", "url"):
        assert label in DEFAULT_GLINER_LABELS

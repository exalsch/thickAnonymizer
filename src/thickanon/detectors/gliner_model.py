"""Find, load and cache the GLiNER model (ONNX, run by onnxruntime)."""
from pathlib import Path

from thickanon.core.types import DEFAULT_GLINER_MODEL_ID, DEFAULT_GLINER_REVISION

_model_cache = {}

# The files the runner needs. The model repo has several other exports
# (fp16, int8, q4 ...); the int8 one was measured to be broken, so only the
# fp32 file is fetched.
_REQUIRED = ("gliner_config.json", "tokenizer.json")

_GPU_PROVIDERS = ("CUDAExecutionProvider", "DmlExecutionProvider")


def _model_key(cfg):
    return (cfg.model_id, cfg.model_path, cfg.onnx_file, cfg.gpu)


def load_model(cfg):
    """Return a cached GLiNER model for this config (built once per process)."""
    key = _model_key(cfg)
    if key not in _model_cache:
        _model_cache[key] = _build_model(cfg)
    return _model_cache[key]


def _snapshot_download(repo_id, revision, allow_patterns, local_files_only=False):
    from huggingface_hub import snapshot_download
    return snapshot_download(repo_id, revision=revision, allow_patterns=allow_patterns,
                             local_files_only=local_files_only)


def resolve_model_dir(cfg) -> Path:
    """The local folder that holds the model files.

    A configured model_path is used as it is. Otherwise the model comes from
    the Hugging Face cache, and is downloaded only when it is not there yet,
    so an offline run with a cached model never touches the network.
    """
    files = list(_REQUIRED) + [cfg.onnx_file]
    if cfg.model_path:
        folder = Path(cfg.model_path)
    else:
        revision = DEFAULT_GLINER_REVISION if cfg.model_id == DEFAULT_GLINER_MODEL_ID else None
        try:
            folder = Path(_snapshot_download(cfg.model_id, revision, files, local_files_only=True))
        except Exception:
            folder = Path(_snapshot_download(cfg.model_id, revision, files))
    missing = [name for name in files if not (folder / name).is_file()]
    if missing:
        raise RuntimeError(
            f"The GLiNER model folder {folder} is missing {', '.join(missing)}. "
            "It needs an ONNX export of the model (gliner_config.json, tokenizer.json "
            f"and {cfg.onnx_file}).")
    return folder


def providers_for(cfg) -> list[str]:
    import onnxruntime
    if not cfg.gpu:
        return ["CPUExecutionProvider"]
    available = [p for p in _GPU_PROVIDERS if p in onnxruntime.get_available_providers()]
    if not available:
        raise RuntimeError(
            "GPU mode needs a GPU build of onnxruntime (onnxruntime-gpu for NVIDIA CUDA, "
            "or onnxruntime-directml). Only the CPU runtime is installed.")
    return available + ["CPUExecutionProvider"]


def _build_model(cfg):
    try:
        import onnxruntime  # noqa: F401
        import tokenizers  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(
            "GLiNER mode requires the 'onnxruntime' and 'tokenizers' packages. "
            "Install them (pip install onnxruntime tokenizers) or disable GLiNER mode."
        ) from exc
    from thickanon.detectors.gliner_onnx import OnnxGliner
    return OnnxGliner.from_dir(resolve_model_dir(cfg), cfg.onnx_file, providers_for(cfg))

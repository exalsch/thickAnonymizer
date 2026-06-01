import hashlib, pytest
from pathlib import Path
from thickanon.core.types import LLMConfig
from thickanon.detectors.llm_model import ensure_model

def _make_src(tmp_path):
    src = tmp_path / "src.gguf"; src.write_bytes(b"GGUF-FAKE-WEIGHTS")
    digest = hashlib.sha256(src.read_bytes()).hexdigest()
    return src, digest

def test_downloads_and_verifies(tmp_path):
    src, digest = _make_src(tmp_path)
    cache = tmp_path / "cache"
    cfg = LLMConfig(model_url=src.as_uri(), sha256=digest, model_path=str(cache / "m.gguf"))
    out = ensure_model(cfg)
    assert Path(out).exists() and Path(out).read_bytes() == b"GGUF-FAKE-WEIGHTS"

def test_checksum_mismatch_raises(tmp_path):
    src, _ = _make_src(tmp_path)
    cfg = LLMConfig(model_url=src.as_uri(), sha256="deadbeef", model_path=str(tmp_path / "m.gguf"))
    with pytest.raises(ValueError):
        ensure_model(cfg)

def test_existing_cached_file_not_redownloaded(tmp_path):
    src, digest = _make_src(tmp_path)
    dest = tmp_path / "m.gguf"; dest.write_bytes(b"GGUF-FAKE-WEIGHTS")
    cfg = LLMConfig(model_url="file:///does-not-exist", sha256=digest, model_path=str(dest))
    # already present + matches checksum -> returns without touching the (bad) URL
    assert Path(ensure_model(cfg)) == dest

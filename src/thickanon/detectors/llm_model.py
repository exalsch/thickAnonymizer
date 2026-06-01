import hashlib
import urllib.request
from pathlib import Path


def _default_cache_path(url: str) -> Path:
    name = url.rsplit("/", 1)[-1] or "model.gguf"
    return Path.home() / ".thickanon" / "models" / name


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def ensure_model(llm_config) -> Path:
    """Return a local path to the GGUF, downloading + verifying if needed."""
    dest = Path(llm_config.model_path) if llm_config.model_path else _default_cache_path(llm_config.model_url)
    want = (llm_config.sha256 or "").lower()
    if dest.exists():
        if not want or _sha256(dest) == want:
            return dest  # cached and valid (or verification disabled)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    urllib.request.urlretrieve(llm_config.model_url, tmp)  # noqa: S310 (local/trusted URL)
    if want and _sha256(tmp) != want:
        tmp.unlink(missing_ok=True)
        raise ValueError("downloaded model failed sha256 verification")
    tmp.replace(dest)
    return dest

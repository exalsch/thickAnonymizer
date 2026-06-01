import hashlib
import urllib.request
import warnings
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
    if not want:
        warnings.warn(
            "downloading model without sha256 verification "
            f"({llm_config.model_url}); pin LLMConfig.sha256 to verify integrity",
            stacklevel=2,
        )
    urllib.request.urlretrieve(llm_config.model_url, tmp)  # noqa: S310 (local/trusted URL)
    if want and _sha256(tmp) != want:
        tmp.unlink(missing_ok=True)
        raise ValueError("downloaded model failed sha256 verification")
    tmp.replace(dest)
    return dest


# GBNF grammar constraining output to a JSON array of {"type","text"} objects.
_JSON_GRAMMAR = r'''
root   ::= "[" ws (obj (ws "," ws obj)*)? ws "]"
obj    ::= "{" ws "\"type\"" ws ":" ws string ws "," ws "\"text\"" ws ":" ws string ws "}"
string ::= "\"" ([^"\\] | "\\" .)* "\""
ws     ::= [ \t\n]*
'''

_runner_cache = {}


def _runner_key(llm_config):
    return (llm_config.model_path, llm_config.model_url,
            llm_config.sha256, llm_config.n_gpu_layers)


def load_runner(llm_config):
    """Return a cached Callable[[str], str] for this config (built once per process)."""
    key = _runner_key(llm_config)
    if key not in _runner_cache:
        _runner_cache[key] = _build_runner(llm_config)
    return _runner_cache[key]


def _build_runner(llm_config):
    """Build a Callable[[str], str] that runs the local model on a prompt.

    Raises RuntimeError with a clear message if llama-cpp-python is unavailable."""
    model_path = ensure_model(llm_config)
    try:
        from llama_cpp import Llama, LlamaGrammar
    except ImportError as exc:
        raise RuntimeError(
            "LLM mode requires llama-cpp-python. Install it (pip install "
            "llama-cpp-python) or disable LLM mode."
        ) from exc
    llm = Llama(model_path=str(model_path), n_gpu_layers=llm_config.n_gpu_layers,
                n_ctx=8192, verbose=False)
    grammar = LlamaGrammar.from_string(_JSON_GRAMMAR)

    def runner(prompt: str) -> str:
        out = llm.create_completion(prompt, max_tokens=1024, temperature=0.0,
                                    grammar=grammar)
        return out["choices"][0]["text"]

    return runner

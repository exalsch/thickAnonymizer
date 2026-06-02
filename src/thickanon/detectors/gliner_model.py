_model_cache = {}


def _model_key(cfg):
    return (cfg.model_id, cfg.model_path, cfg.gpu)


def load_model(cfg):
    """Return a cached fast_gliner model for this config (built once per process)."""
    key = _model_key(cfg)
    if key not in _model_cache:
        _model_cache[key] = _build_model(cfg)
    return _model_cache[key]


def _build_model(cfg):
    try:
        import fast_gliner
    except ImportError as exc:
        raise RuntimeError(
            "GLiNER mode requires fast_gliner. Install it (pip install fast_gliner) "
            "or disable GLiNER mode."
        ) from exc
    # Verify this matches the installed fast_gliner API; adapt minimally if needed.
    source = cfg.model_path or cfg.model_id
    return fast_gliner.GLiNER.from_pretrained(source)

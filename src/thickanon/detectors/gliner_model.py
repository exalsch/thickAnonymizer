_model_cache = {}


def _model_key(cfg):
    return (cfg.model_id, cfg.model_path, cfg.gpu)


def load_model(cfg):
    """Return a cached GLiNER model for this config (built once per process)."""
    key = _model_key(cfg)
    if key not in _model_cache:
        _model_cache[key] = _build_model(cfg)
    return _model_cache[key]


def _build_model(cfg):
    try:
        from gliner import GLiNER
    except ImportError as exc:
        raise RuntimeError(
            "GLiNER mode requires the 'gliner' package. Install it (pip install gliner) "
            "or disable GLiNER mode."
        ) from exc
    source = cfg.model_path or cfg.model_id
    model = GLiNER.from_pretrained(source)
    if cfg.gpu:
        model = model.to("cuda")
    return model

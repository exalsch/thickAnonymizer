# GLiNER-PII Detector Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the generative-LLM detector with a GLiNER neural NER detector via `fast_gliner` (Rust/ONNX, torch-free), feeding native offsets + real confidence scores into the existing Entity pipeline.

**Architecture:** New `detectors/gliner.py` (chunk → `model.predict_entities(chunk, labels, threshold)` → Entity, offset-shift + dedup) and `detectors/gliner_model.py` (cached fast_gliner model load; hard error if missing). `engine.detect()` swaps its `config.llm` branch for a `config.gliner` branch (regex+denylist+GLiNER, no spaCy). The order keeps the suite green: build the new backend, switch engine/CLI/UI to it, then delete the old LLM backend last.

**Tech Stack:** Python 3.11+ (running 3.13), fast_gliner (ONNX GLiNER inference, prebuilt CPU wheel, no torch), existing Presidio/regex/spaCy default path.

**Key shared types & contracts:**
- `GLiNERConfig` (Task 1) on `AnonymizeConfig.gliner` (default `None`).
- `gliner_detect(text, cfg, model) -> list[Entity]` (Task 2); `model` injected (stub in tests).
- `load_model(cfg) -> object` and `_build_model(cfg)` (Task 3), cached per process.
- Reuses existing `detectors/normalize.py::normalize_type` and `core/types.Entity`.

**fast_gliner API (from research — verify against the installed package in Tasks 3/7):**
`model.predict_entities(text, labels, threshold=0.5)` → `list[{"text","label","score","start","end"}]` with character offsets and a 0–1 score. The model is loaded from a Hugging Face ONNX GLiNER repo.

**Existing code reused/kept:** `detectors/normalize.py`, `detectors/recognizers.py`, `detectors/engine.py` (`_base_analyzer`, `_resolve_overlaps`, `_regex_denylist_entities`), `core/orchestrator.py`, `cli.py`, `ui/api.py`. The LLM backend (`detectors/llm.py`, `detectors/llm_model.py`, `LLMConfig`, `AnonymizeConfig.llm`, `[llm]` extra) is removed in Task 7.

---

### Task 1: GLiNERConfig

**Files:**
- Modify: `src/thickanon/core/types.py`
- Test: `tests/core/test_gliner_config.py`

Added alongside the existing `LLMConfig` (removed in Task 7). `AnonymizeConfig` keeps its `llm` field and gains a `gliner` field.

- [ ] **Step 1: Write the failing test**

```python
# tests/core/test_gliner_config.py
from thickanon.core.types import AnonymizeConfig, GLiNERConfig, DEFAULT_GLINER_LABELS

def test_gliner_defaults():
    c = GLiNERConfig()
    assert c.enabled is False
    assert c.threshold == 0.5
    assert c.gpu is False
    assert c.max_chunk_chars > 0
    assert c.labels == DEFAULT_GLINER_LABELS
    assert isinstance(c.model_id, str) and c.model_id

def test_anonymizeconfig_has_optional_gliner():
    assert AnonymizeConfig().gliner is None
    assert AnonymizeConfig(gliner=GLiNERConfig(enabled=True)).gliner.enabled is True

def test_independent_label_lists():
    a, b = GLiNERConfig(), GLiNERConfig()
    a.labels.append("extra")
    assert "extra" not in b.labels
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/core/test_gliner_config.py -v`
Expected: FAIL — `ImportError: cannot import name 'GLiNERConfig'`

- [ ] **Step 3: Write implementation (append to `core/types.py`)**

```python
DEFAULT_GLINER_LABELS = [
    "person", "organization", "location", "email", "phone number",
    "address", "date of birth", "job title", "account number", "id number",
]

# A fast_gliner-supported ONNX GLiNER model on Hugging Face. Implementer: confirm
# this repo loads with fast_gliner (Task 3/7); if not, pin another ONNX GLiNER repo.
DEFAULT_GLINER_MODEL_ID = "onnx-community/gliner_multi_pii-v1"

@dataclass
class GLiNERConfig:
    enabled: bool = False
    model_id: str = DEFAULT_GLINER_MODEL_ID
    model_path: str | None = None
    labels: list[str] = field(default_factory=lambda: list(DEFAULT_GLINER_LABELS))
    threshold: float = 0.5
    gpu: bool = False
    max_chunk_chars: int = 4000
```

Add `gliner: "GLiNERConfig | None" = None` as a field of `AnonymizeConfig` (keep the
existing `llm` field for now — it is removed in Task 7).

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/core/test_gliner_config.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/thickanon/core/types.py tests/core/test_gliner_config.py
git commit -m "feat: GLiNERConfig and AnonymizeConfig.gliner"
```

---

### Task 2: gliner_detect (chunk → predict → Entity)

**Files:**
- Create: `src/thickanon/detectors/gliner.py`
- Test: `tests/detectors/test_gliner_detect.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/detectors/test_gliner_detect.py
from thickanon.core.types import GLiNERConfig
from thickanon.detectors.gliner import gliner_detect

class StubModel:
    """Returns canned spans; ignores chunk text."""
    def __init__(self, items): self.items = items
    def predict_entities(self, text, labels, threshold=0.5):
        return list(self.items)

class FindStub:
    """Finds a needle in each chunk and returns its real chunk-local offsets."""
    def __init__(self, needle, label="person", score=0.9):
        self.needle, self.label, self.score = needle, label, score
    def predict_entities(self, text, labels, threshold=0.5):
        i = text.find(self.needle)
        if i == -1: return []
        return [{"label": self.label, "text": self.needle,
                 "start": i, "end": i + len(self.needle), "score": self.score}]

def test_offsets_score_and_type_normalized():
    text = "Patient John Carter at Berlin"   # John Carter @8..19, Berlin @23..29
    model = StubModel([
        {"label": "person", "text": "John Carter", "start": 8, "end": 19, "score": 0.9},
        {"label": "phone number", "text": "Berlin", "start": 23, "end": 29, "score": 0.8},
    ])
    ents = gliner_detect(text, GLiNERConfig(threshold=0.5), model)
    by = {e.entity_type: e for e in ents}
    assert text[by["PERSON"].start:by["PERSON"].end] == "John Carter"
    assert by["PERSON"].score == 0.9
    assert "PHONE_NUMBER" in by                       # "phone number" -> normalized

def test_below_threshold_dropped():
    model = StubModel([{"label": "person", "text": "x", "start": 0, "end": 1, "score": 0.3}])
    assert gliner_detect("x", GLiNERConfig(threshold=0.5), model) == []

def test_dedupes_across_chunks():
    text = "John " * 50
    ents = gliner_detect(text, GLiNERConfig(max_chunk_chars=40), FindStub("John"))
    spans = [(e.start, e.end) for e in ents]
    assert spans and len(spans) == len(set(spans))   # no duplicate global spans

def test_out_of_range_offsets_skipped():
    model = StubModel([{"label": "person", "text": "zz", "start": 99, "end": 101, "score": 0.9}])
    assert gliner_detect("short", GLiNERConfig(), model) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/detectors/test_gliner_detect.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write implementation**

```python
# src/thickanon/detectors/gliner.py
from thickanon.core.types import Entity
from thickanon.detectors.normalize import normalize_type


def iter_chunks(text: str, max_chars: int, overlap: int = 200) -> list[tuple[int, str]]:
    """Split text into overlapping windows of at most max_chars; (base, chunk)."""
    if not text:
        return []
    if len(text) <= max_chars:
        return [(0, text)]
    overlap = max(0, min(overlap, max_chars // 2))
    step = max(1, max_chars - overlap)
    chunks, pos = [], 0
    while pos < len(text):
        chunks.append((pos, text[pos:pos + max_chars]))
        if pos + max_chars >= len(text):
            break
        pos += step
    return chunks


def gliner_detect(text: str, cfg, model) -> list[Entity]:
    """Run GLiNER over (chunked) text, returning Entity spans with native offsets
    and scores. `model.predict_entities(chunk, labels, threshold)` returns dicts
    with label/text/start/end/score. `model` is injected so tests need no real model."""
    seen, out = set(), []
    for base, chunk in iter_chunks(text, cfg.max_chunk_chars):
        for sp in model.predict_entities(chunk, cfg.labels, threshold=cfg.threshold):
            score = sp.get("score", 0.0)
            if score < cfg.threshold:
                continue
            start, end = sp.get("start"), sp.get("end")
            if not isinstance(start, int) or not isinstance(end, int):
                continue
            if start < 0 or end > len(chunk) or start >= end:
                continue  # defensive: offsets must be valid within the chunk
            surface = chunk[start:end]
            etype = normalize_type(sp["label"])
            gstart, gend = base + start, base + end
            key = (etype, gstart, gend)
            if key in seen:
                continue
            seen.add(key)
            out.append(Entity(gstart, gend, etype, score, surface))
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/detectors/test_gliner_detect.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/thickanon/detectors/gliner.py tests/detectors/test_gliner_detect.py
git commit -m "feat: gliner_detect (chunk -> predict_entities -> Entity, offsets+score)"
```

---

### Task 3: gliner_model (cached load + hard error)

**Files:**
- Create: `src/thickanon/detectors/gliner_model.py`
- Test: `tests/detectors/test_gliner_model.py`

`load_model` builds the fast_gliner model and caches it per process. The exact
fast_gliner load call is verified against the installed package; the unit test only
covers the missing-dependency error and the cache (both independent of the real API).

- [ ] **Step 1: Write the failing test**

```python
# tests/detectors/test_gliner_model.py
import builtins, pytest
from thickanon.core.types import GLiNERConfig
from thickanon.detectors import gliner_model

def test_load_model_raises_clear_error_without_fast_gliner(monkeypatch):
    real_import = builtins.__import__
    def fake_import(name, *a, **k):
        if name == "fast_gliner" or name.startswith("fast_gliner."):
            raise ImportError("no fast_gliner")
        return real_import(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(RuntimeError) as exc:
        gliner_model.load_model(GLiNERConfig(model_id="x"))
    assert "fast_gliner" in str(exc.value)

def test_load_model_is_cached_per_config(monkeypatch):
    monkeypatch.setattr(gliner_model, "_model_cache", {})
    calls = []
    monkeypatch.setattr(gliner_model, "_build_model",
                        lambda cfg: calls.append(1) or object())
    m1 = gliner_model.load_model(GLiNERConfig(model_id="a"))
    m2 = gliner_model.load_model(GLiNERConfig(model_id="a"))   # same key
    m3 = gliner_model.load_model(GLiNERConfig(model_id="b"))   # different key
    assert m1 is m2 and len(calls) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/detectors/test_gliner_model.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write implementation**

```python
# src/thickanon/detectors/gliner_model.py
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
```

> Implementer note: confirm `fast_gliner.GLiNER.from_pretrained(source)` is the correct
> load call and how to request GPU (e.g. a device/`gpu` argument or the `[cuda]` wheel).
> If the real API differs, adapt only `_build_model` and pass `cfg.gpu` appropriately;
> the unit tests (import-error + cache) are unaffected. Report what you changed.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/detectors/test_gliner_model.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/thickanon/detectors/gliner_model.py tests/detectors/test_gliner_model.py
git commit -m "feat: cached fast_gliner model loader with hard error when missing"
```

---

### Task 4: Wire the GLiNER branch into engine.detect()

**Files:**
- Modify: `src/thickanon/detectors/engine.py`
- Test: `tests/detectors/test_engine_gliner.py`

`engine.py` currently has an LLM branch: `if config.llm is not None and config.llm.enabled:`
using `_regex_denylist_entities`, `llm_model.load_runner`, `llm_detect`. Replace that branch
with a GLiNER branch. (The LLM imports/branch are removed here; `llm.py`/`llm_model.py` files
are deleted in Task 7.)

- [ ] **Step 1: Write the failing test**

```python
# tests/detectors/test_engine_gliner.py
from thickanon.core.types import AnonymizeConfig, GLiNERConfig
from thickanon.detectors import gliner_model
from thickanon.detectors.engine import detect

class StubModel:
    def predict_entities(self, text, labels, threshold=0.5):
        i = text.find("John Carter")
        return ([{"label": "person", "text": "John Carter",
                  "start": i, "end": i + 11, "score": 0.9}] if i != -1 else [])

def test_gliner_branch_merges_regex_and_gliner(monkeypatch):
    monkeypatch.setattr(gliner_model, "load_model", lambda cfg: StubModel())
    text = "John Carter emailed jane@acme.com from 10.0.0.5"
    cfg = AnonymizeConfig(gliner=GLiNERConfig(enabled=True), low_threshold=0.35)
    ents = detect(text, cfg)
    labels = {e.entity_type for e in ents}
    assert {"PERSON", "EMAIL", "IP"} <= labels
    for e in ents:
        assert text[e.start:e.end] == e.text

def test_gliner_disabled_uses_spacy_path():
    ents = detect("John at 10.0.0.1", AnonymizeConfig())
    assert {"IP"} <= {e.entity_type for e in ents}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/detectors/test_engine_gliner.py -v`
Expected: FAIL — GLiNER branch not implemented

- [ ] **Step 3: Write implementation (modify `engine.py`)**

Replace the LLM imports
```python
from thickanon.detectors import llm_model
from thickanon.detectors.llm import llm_detect
```
with
```python
from thickanon.detectors import gliner_model
from thickanon.detectors.gliner import gliner_detect
```

Replace the LLM branch in `detect()` with the GLiNER branch (keep everything else):

```python
def detect(text: str, config: AnonymizeConfig) -> list[Entity]:
    if config.gliner is not None and config.gliner.enabled:
        entities = _regex_denylist_entities(text, config)
        model = gliner_model.load_model(config.gliner)
        entities += gliner_detect(text, config.gliner, model)
    else:
        analyzer = _base_analyzer(config.language)
        ad_hoc = [deny_list_recognizer(config.deny_list)] if config.deny_list else []
        raw = analyzer.analyze(text=text, language=config.language, ad_hoc_recognizers=ad_hoc)
        entities = [Entity(r.start, r.end, normalize_type(r.entity_type), r.score,
                           text[r.start:r.end]) for r in raw]
    entities = [e for e in entities if e.score >= config.low_threshold]
    return _resolve_overlaps(entities)
```

(`_regex_denylist_entities`, `_base_analyzer`, `_resolve_overlaps`, `normalize_type`,
`deny_list_recognizer`, `Entity` are already present.) Reference `gliner_model.load_model`
via the MODULE so tests can monkeypatch it.

Note: `tests/detectors/test_engine_llm.py` still references the removed LLM branch and will
now fail. DELETE `tests/detectors/test_engine_llm.py` in this task (its behavior is replaced
by `test_engine_gliner.py`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/detectors/ tests/core/ -q`
Expected: PASS (new gliner-branch tests; existing engine/recognizer/normalize tests green).
The old `llm.py`/`llm_model.py` and their tests still exist and still pass at this point — they
are deleted in Task 7.

- [ ] **Step 5: Commit**

```bash
git add src/thickanon/detectors/engine.py tests/detectors/test_engine_gliner.py
git rm tests/detectors/test_engine_llm.py
git commit -m "feat: engine GLiNER branch (regex+denylist+GLiNER, no spaCy when enabled)"
```

---

### Task 5: CLI — replace --llm flags with --gliner flags

**Files:**
- Modify: `src/thickanon/cli.py`
- Test: `tests/test_cli_gliner.py`
- Delete: `tests/test_cli_llm.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli_gliner.py
from thickanon.cli import main
from thickanon.detectors import gliner_model

class StubModel:
    def predict_entities(self, text, labels, threshold=0.5):
        i = text.find("John Carter")
        return ([{"label": "person", "text": "John Carter",
                  "start": i, "end": i + 11, "score": 0.9}] if i != -1 else [])

def test_cli_gliner_flag_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(gliner_model, "load_model", lambda cfg: StubModel())
    root = tmp_path / "data"; root.mkdir()
    f = root / "x.txt"; f.write_text("John Carter pinged 10.0.0.7", encoding="utf-8")
    mp = tmp_path / "map.json"
    rc = main(["anon", str(f), "--root", str(root), "--mapping", str(mp),
               "--mode", "auto_redact", "--gliner",
               "--gliner-labels", "person,location", "--gliner-threshold", "0.4"])
    assert rc == 0
    out = f.read_text(encoding="utf-8")
    assert "John Carter" not in out and "10.0.0.7" not in out

def test_cli_download_model(tmp_path, monkeypatch, capsys):
    called = {}
    monkeypatch.setattr(gliner_model, "load_model",
                        lambda cfg: called.setdefault("m", object()))
    rc = main(["download-model"])
    assert rc == 0 and "m" in called
    assert "ready" in capsys.readouterr().out.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli_gliner.py -v`
Expected: FAIL — unrecognized `--gliner` / download-model uses old path

- [ ] **Step 3: Write implementation (modify `cli.py`)**

Change the import `from thickanon.core.types import AnonymizeConfig, ReviewMode, LLMConfig`
to `from thickanon.core.types import AnonymizeConfig, ReviewMode, GLiNERConfig`, and
`from thickanon.detectors import llm_model` to `from thickanon.detectors import gliner_model`.

Replace the four `--llm*` arguments on the `anonymize` subparser with:
```python
    a.add_argument("--gliner", action="store_true", help="use the GLiNER neural detector")
    a.add_argument("--gliner-model", help="path to a local GLiNER model dir")
    a.add_argument("--gliner-labels", help="comma-separated entity labels to detect")
    a.add_argument("--gliner-threshold", type=float, default=0.5)
    a.add_argument("--gliner-gpu", action="store_true")
```

In the anonymize branch, replace the `llm_cfg` block with:
```python
        gliner_cfg = None
        if ns.gliner:
            kw = {"enabled": True, "model_path": ns.gliner_model,
                  "threshold": ns.gliner_threshold, "gpu": ns.gliner_gpu}
            if ns.gliner_labels:
                kw["labels"] = [s.strip() for s in ns.gliner_labels.split(",") if s.strip()]
            gliner_cfg = GLiNERConfig(**kw)
        cfg = AnonymizeConfig(mode=ReviewMode(ns.mode), deny_list=ns.deny, gliner=gliner_cfg)
```

Replace the `download-model` handler body with:
```python
    if ns.action == "download-model":
        gliner_model.load_model(GLiNERConfig(model_path=getattr(ns, "gliner_model", None)))
        print("Model ready (downloaded/cached).")
        return 0
```
and on the `download-model` subparser change `--llm-model` to `--gliner-model`.

Delete the old LLM CLI test: `git rm tests/test_cli_llm.py`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_cli_gliner.py -v` then `pytest -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/thickanon/cli.py tests/test_cli_gliner.py
git rm tests/test_cli_llm.py
git commit -m "feat: CLI --gliner flags and GLiNER download-model"
```

---

### Task 6: UI — replace LLM wiring with GLiNER wiring

**Files:**
- Modify: `src/thickanon/ui/api.py`
- Modify: `src/thickanon/ui/web/index.html`
- Test: `tests/ui/test_api_gliner.py`
- Delete: `tests/ui/test_api_llm.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/ui/test_api_gliner.py
from thickanon.ui.api import Api
from thickanon.detectors import gliner_model

class StubModel:
    def predict_entities(self, text, labels, threshold=0.5):
        i = text.find("John Carter")
        return ([{"label": "person", "text": "John Carter",
                  "start": i, "end": i + 11, "score": 0.9}] if i != -1 else [])

def test_api_anonymize_with_gliner(tmp_path, monkeypatch):
    monkeypatch.setattr(gliner_model, "load_model", lambda cfg: StubModel())
    root = tmp_path / "data"; root.mkdir()
    f = root / "n.txt"; f.write_text("John Carter at 10.0.0.3", encoding="utf-8")
    res = Api().anonymize(files=[str(f)], root=str(root),
                          mapping_path=str(tmp_path / "m.json"), mode="auto_redact",
                          deny=[], backup_dir=None, passphrase=None,
                          gliner=True, gliner_labels="person,location",
                          gliner_threshold=0.4, gliner_gpu=False)
    assert res["ok"] is True
    assert "John Carter" not in f.read_text(encoding="utf-8")

def test_api_download_model(monkeypatch):
    monkeypatch.setattr(gliner_model, "load_model", lambda cfg: object())
    res = Api().download_model()
    assert res["ok"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/ui/test_api_gliner.py -v`
Expected: FAIL — `anonymize() got an unexpected keyword argument 'gliner'`

- [ ] **Step 3: Write implementation**

In `ui/api.py`: change the types import to include `GLiNERConfig` (drop `LLMConfig`), and
`from thickanon.detectors import gliner_model` (drop `llm_model`). Change `anonymize` to:

```python
    def anonymize(self, files, root, mapping_path, mode, deny, backup_dir, passphrase,
                  gliner=False, gliner_labels="", gliner_threshold=0.5, gliner_gpu=False):
        try:
            # ... KEEP existing root inference + default mapping + ensure_mapping_outside_root ...
            gliner_cfg = None
            if gliner:
                kw = {"enabled": True, "threshold": gliner_threshold, "gpu": gliner_gpu}
                labels = [s.strip() for s in (gliner_labels or "").split(",") if s.strip()]
                if labels:
                    kw["labels"] = labels
                gliner_cfg = GLiNERConfig(**kw)
            cfg = AnonymizeConfig(mode=ReviewMode(mode), deny_list=deny or [], gliner=gliner_cfg)
            # ... KEEP rest unchanged (anonymize_paths(..., cfg, ...), mapping.save, return) ...
```

Replace the `download_model` method body to use gliner:
```python
    def download_model(self):
        try:
            gliner_model.load_model(GLiNERConfig())
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
```

In `web/index.html`, replace the LLM block (checkbox `#llm`, `#llm_instr`, `#llm_gpu`) with:
```html
 <label><input type="checkbox" id="gliner"> Use neural NER (GLiNER, higher recall)</label>
 <div class="row">
   <div><label>Labels (comma-separated)</label><input id="gliner_labels" placeholder="person, organization, email"></div>
   <div><label>Threshold</label><input id="gliner_thr" type="number" step="0.05" value="0.5"></div>
 </div>
 <label><input type="checkbox" id="gliner_gpu"> Use GPU (needs CUDA build)</label>
 <button class="ghost" onclick="downloadModel()">Download GLiNER model</button>
```
Change the `anonymize` JS call's trailing args from the old LLM trio to:
`, $('gliner').checked, $('gliner_labels').value, parseFloat($('gliner_thr').value)||0.5, $('gliner_gpu').checked`
(`downloadModel()` already calls `window.pywebview.api.download_model()` — leave it.)

Delete the old LLM UI test: `git rm tests/ui/test_api_llm.py`.

- [ ] **Step 4: Run test to verify it passes + import check**

Run: `pytest tests/ui/test_api_gliner.py -v` then `python -c "import thickanon.ui.app, thickanon.ui.api"`
Expected: PASS; import OK

- [ ] **Step 5: Commit**

```bash
git add src/thickanon/ui/api.py src/thickanon/ui/web/index.html tests/ui/test_api_gliner.py
git rm tests/ui/test_api_llm.py
git commit -m "feat: UI GLiNER toggle, labels, threshold, gpu, download"
```

---

### Task 7: Remove LLM backend; build config + gated integration + docs

**Files:**
- Delete: `src/thickanon/detectors/llm.py`, `src/thickanon/detectors/llm_model.py`
- Delete: `tests/detectors/test_llm_prompt.py`, `test_llm_parse.py`, `test_llm_resolve.py`, `test_llm_chunk.py`, `test_llm_detect.py`, `test_llm_model_cache.py`, `test_llm_runner.py`
- Delete: `tests/integration/test_llm_real.py`
- Modify: `src/thickanon/core/types.py` (remove `LLMConfig`, `DEFAULT_LLM_*`, `AnonymizeConfig.llm`)
- Modify: `pyproject.toml` (remove `[llm]` extra, add `[gliner]`)
- Modify: `packaging/thickanon.spec` (remove llama_cpp bundling, add guarded fast_gliner)
- Modify: `README.md`
- Test: `tests/integration/test_gliner_real.py`

- [ ] **Step 1: Delete the LLM modules and their tests**

```bash
git rm src/thickanon/detectors/llm.py src/thickanon/detectors/llm_model.py \
  tests/detectors/test_llm_prompt.py tests/detectors/test_llm_parse.py \
  tests/detectors/test_llm_resolve.py tests/detectors/test_llm_chunk.py \
  tests/detectors/test_llm_detect.py tests/detectors/test_llm_model_cache.py \
  tests/detectors/test_llm_runner.py tests/integration/test_llm_real.py
```

- [ ] **Step 2: Remove LLM config from `core/types.py`**

Delete `DEFAULT_LLM_CATEGORIES`, `DEFAULT_LLM_MODEL_URL`, `DEFAULT_LLM_SHA256`, the
`LLMConfig` dataclass, and the `llm: "LLMConfig | None" = None` field on `AnonymizeConfig`.
Also delete `tests/core/test_llm_config.py`:

```bash
git rm tests/core/test_llm_config.py
```

- [ ] **Step 3: Run the suite to confirm nothing references the removed LLM code**

Run: `pytest -q`
Expected: PASS (no import errors; every LLM reference is gone). If anything fails to import
`llm`/`LLMConfig`, fix that reference (there should be none after Tasks 4–6).

- [ ] **Step 4: Write the gated integration test**

```python
# tests/integration/test_gliner_real.py
import os, pytest
from thickanon.core.types import AnonymizeConfig, GLiNERConfig
from thickanon.detectors.engine import detect

pytestmark = pytest.mark.skipif(
    os.environ.get("THICKANON_GLINER_IT") != "1",
    reason="set THICKANON_GLINER_IT=1 to run the real-model integration test",
)

def test_real_model_detects_name():
    cfg = AnonymizeConfig(gliner=GLiNERConfig(enabled=True))  # downloads default model
    ents = detect("Please contact Dr. Eleanor Whitfield about the case.", cfg)
    assert any(e.entity_type == "PERSON" and "Whitfield" in e.text for e in ents)
```

Run `pytest tests/integration/test_gliner_real.py -v` → expect SKIPPED (no fast_gliner needed to skip).

- [ ] **Step 5: pyproject.toml — swap the extras**

Remove `llm = ["llama-cpp-python"]`. Add `gliner = ["fast_gliner"]` under
`[project.optional-dependencies]`.

- [ ] **Step 6: PyInstaller spec — swap the guarded bundling**

In `packaging/thickanon.spec`, remove the guarded `collect_all("llama_cpp")` block and add:
```python
# Optional GLiNER backend: bundle fast_gliner only if installed. Default build is
# CPU-only; GLiNER mode requires installing the [gliner] extra before building.
try:
    _d, _b, _h = collect_all("fast_gliner")
    datas += _d; binaries += _b; hiddenimports += _h
except Exception:
    pass
```

- [ ] **Step 7: README — replace the LLM section with a GLiNER section**

Replace the "Local LLM detection (optional)" section with "Neural NER detection (GLiNER,
optional)": install with `pip install -e ".[dev,gliner]"` (or `pip install fast_gliner`,
prebuilt CPU wheel, no torch/Rust toolchain); enable with `--gliner` / the UI toggle;
configurable `--gliner-labels` and `--gliner-threshold`; first run downloads the ONNX
GLiNER model (or `thickanon download-model`); model loads once per process (pass a folder);
`--gliner-gpu` needs the `fast_gliner[cuda]` wheel; GLiNER scores feed the normal review
bands; enabled-but-unloadable is a hard error.

- [ ] **Step 8: (manual, optional) verify the real model**

Run `pip install fast_gliner`; if it installs, run
`THICKANON_GLINER_IT=1 pytest tests/integration/test_gliner_real.py -v` to confirm the
pinned `DEFAULT_GLINER_MODEL_ID` loads via fast_gliner and detects the name. If the model
id is not fast_gliner-loadable, pin a working ONNX GLiNER repo in `DEFAULT_GLINER_MODEL_ID`
(`core/types.py`) and re-run. Record the outcome (and any model_id change) in the commit.

- [ ] **Step 9: Full suite + commit**

Run: `pytest -q`
Expected: PASS (all unit tests + integration SKIPPED).

```bash
git add -A
git commit -m "build: remove llama.cpp LLM backend, add fast_gliner [gliner] extra, gated GLiNER integration test, docs"
```

---

## Self-review notes

- **Spec coverage:** fast_gliner backend (T2, T3, T7), replaces-spaCy with regex+denylist-always
  (T4), configurable labels + threshold (T1, T2, T5, T6), real-score banding (T2 keeps score →
  existing bands), native offsets + defensive offset guard (T2), GPU config (T1, T3, T5, T6),
  off-by-default + hard-error-when-unloadable (T1, T3, T4), first-run model download via library
  (T3, T5/T6 download-model), chunking + dedup (T2), CLI + UI surface (T5, T6), removal of the
  LLM backend incl. config/extra/spec (T4–T7), gated real-model integration test + `[gliner]`
  extra + guarded bundling (T7), README (T7). All spec sections map to a task.
- **Placeholder scan:** the one deferred concrete value is `DEFAULT_GLINER_MODEL_ID`, handled by
  T3's implementer note and T7 Step 8 (verify/pin a fast_gliner-loadable ONNX GLiNER repo).
  No other placeholders.
- **Type consistency:** `GLiNERConfig` fields (`enabled`, `model_id`, `model_path`, `labels`,
  `threshold`, `gpu`, `max_chunk_chars`), `gliner_detect(text, cfg, model)`,
  `load_model`/`_build_model`/`_model_cache`, `model.predict_entities(text, labels, threshold)`,
  and `normalize_type` are used identically across tasks. `_resolve_overlaps` reused on Entity.
- **Ordering invariant:** Tasks 1–6 keep the suite green while both backends coexist; Task 7
  removes the LLM backend only after nothing references it (Tasks 4–6 already switched engine/
  CLI/UI to `gliner`). The green-keeping is explicit in T4 Step 4 and T7 Step 3.

# On-device LLM Detector Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an optional, local GGUF-model detection layer (llama-cpp-python) that replaces spaCy NER when enabled, feeding context-detected sensitive spans into the existing `Entity` pipeline.

**Architecture:** A new `detectors/llm.py` turns model output into `Entity` objects using offset-via-search (verbatim spans located in the text; hallucinations dropped); `detectors/llm_model.py` handles model download/caching and building the inference callable; `engine.detect()` gains a branch that, when `config.llm.enabled`, runs regex + deny-list + LLM (no spaCy) and merges via the existing overlap resolver. Off by default.

**Tech Stack:** Python 3.11+ (running 3.13), llama-cpp-python (GGUF + GBNF grammar), stdlib urllib/hashlib for download+sha256, existing Presidio/regex stack.

**Key shared types & contracts (defined in early tasks, used throughout):**
- `LLMConfig` (Task 1) — nested in `AnonymizeConfig.llm` (default `None`).
- `normalize_type(t: str) -> str` and `_TYPE_NORMALIZE` live in `detectors/normalize.py` (Task 4), imported by both `engine.py` and `llm.py` (avoids a circular import).
- `resolve_spans(text, items, confidence, base=0) -> list[Entity]` (Task 5) — `items` is a list of `{"type": str, "text": str}`.
- `iter_chunks(text, max_chars) -> list[tuple[int, str]]` (Task 6) — `(base_offset, chunk_text)`.
- `llm_detect(text, llm_config, runner) -> list[Entity]` (Task 7) — `runner` is `Callable[[str], str]` (prompt → raw model text); injectable so tests need no model.
- `ensure_model(llm_config) -> Path` and `load_runner(llm_config) -> Callable[[str], str]` (Tasks 8–9).

**Existing code this builds on (do not rewrite):** `core/types.py` (Entity, ReviewMode, AnonymizeConfig), `detectors/recognizers.py` (`custom_recognizers()`, `deny_list_recognizer()`), `detectors/engine.py` (`_base_analyzer`, `_resolve_overlaps`, `detect()`, currently holds `_TYPE_NORMALIZE`), `core/orchestrator.py`, `cli.py`, `ui/api.py`.

---

### Task 1: LLMConfig

**Files:**
- Modify: `src/thickanon/core/types.py`
- Test: `tests/core/test_llm_config.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/core/test_llm_config.py
from thickanon.core.types import AnonymizeConfig, LLMConfig, DEFAULT_LLM_CATEGORIES

def test_llmconfig_defaults():
    c = LLMConfig()
    assert c.enabled is False
    assert c.n_gpu_layers == 0
    assert c.confidence == 0.5
    assert c.max_chunk_chars > 0
    assert c.categories == DEFAULT_LLM_CATEGORIES
    assert c.custom_instruction == ""

def test_anonymizeconfig_has_optional_llm():
    assert AnonymizeConfig().llm is None
    cfg = AnonymizeConfig(llm=LLMConfig(enabled=True))
    assert cfg.llm.enabled is True

def test_two_configs_have_independent_category_lists():
    a, b = LLMConfig(), LLMConfig()
    a.categories.append("EXTRA")
    assert "EXTRA" not in b.categories
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/core/test_llm_config.py -v`
Expected: FAIL — `ImportError: cannot import name 'LLMConfig'`

- [ ] **Step 3: Write implementation (append to `core/types.py`)**

```python
DEFAULT_LLM_CATEGORIES = [
    "PERSON", "ORGANIZATION", "LOCATION", "JOB_TITLE",
    "DATE_OF_BIRTH", "ACCOUNT_ID",
]

# Pinned default model (small, CPU-friendly). The sha256 is verified on download;
# see detectors/llm_model.py. Implementer: confirm URL resolves and paste the real
# sha256 of the downloaded file into DEFAULT_LLM_SHA256 (Task 8 explains how).
DEFAULT_LLM_MODEL_URL = (
    "https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/"
    "qwen2.5-1.5b-instruct-q4_k_m.gguf"
)
DEFAULT_LLM_SHA256 = ""  # empty = skip verification (logs a warning); pin once known

@dataclass
class LLMConfig:
    enabled: bool = False
    model_path: str | None = None
    model_url: str = DEFAULT_LLM_MODEL_URL
    sha256: str = DEFAULT_LLM_SHA256
    n_gpu_layers: int = 0
    confidence: float = 0.5
    categories: list[str] = field(default_factory=lambda: list(DEFAULT_LLM_CATEGORIES))
    custom_instruction: str = ""
    max_chunk_chars: int = 4000
```

Then add `llm: "LLMConfig | None" = None` as the last field of `AnonymizeConfig`.
(`dataclass` and `field` are already imported at the top of the file.)

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/core/test_llm_config.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/thickanon/core/types.py tests/core/test_llm_config.py
git commit -m "feat: LLMConfig and AnonymizeConfig.llm"
```

---

### Task 2: Prompt builder

**Files:**
- Create: `src/thickanon/detectors/llm.py`
- Test: `tests/detectors/test_llm_prompt.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/detectors/test_llm_prompt.py
from thickanon.detectors.llm import build_prompt

def test_prompt_lists_categories_and_text():
    p = build_prompt("John lives in Berlin", ["PERSON", "LOCATION"], "")
    assert "PERSON" in p and "LOCATION" in p
    assert "John lives in Berlin" in p
    assert "JSON" in p  # instructs JSON output

def test_prompt_includes_custom_instruction():
    p = build_prompt("x", ["PERSON"], "Treat internal codenames as sensitive.")
    assert "internal codenames" in p
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/detectors/test_llm_prompt.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write implementation**

```python
# src/thickanon/detectors/llm.py
def build_prompt(text: str, categories: list[str], custom_instruction: str = "") -> str:
    cats = ", ".join(categories)
    extra = f"\nAdditional guidance: {custom_instruction}" if custom_instruction.strip() else ""
    return (
        "You extract sensitive data spans from text.\n"
        f"Categories to find: {cats}.{extra}\n"
        "Return ONLY a JSON array of objects with keys \"type\" (one of the "
        "categories) and \"text\" (the exact substring, copied verbatim from the "
        "input). Do not include offsets. If nothing is found, return [].\n"
        "----- INPUT -----\n"
        f"{text}\n"
        "----- END INPUT -----"
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/detectors/test_llm_prompt.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/thickanon/detectors/llm.py tests/detectors/test_llm_prompt.py
git commit -m "feat: LLM detection prompt builder"
```

---

### Task 3: Parse model output

**Files:**
- Modify: `src/thickanon/detectors/llm.py`
- Test: `tests/detectors/test_llm_parse.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/detectors/test_llm_parse.py
from thickanon.detectors.llm import parse_items

def test_parses_plain_json_array():
    items = parse_items('[{"type":"PERSON","text":"John"},{"type":"LOCATION","text":"Berlin"}]')
    assert items == [{"type": "PERSON", "text": "John"},
                     {"type": "LOCATION", "text": "Berlin"}]

def test_strips_code_fences():
    items = parse_items('```json\n[{"type":"PERSON","text":"Jo"}]\n```')
    assert items == [{"type": "PERSON", "text": "Jo"}]

def test_malformed_returns_empty():
    assert parse_items("not json at all") == []
    assert parse_items("") == []

def test_drops_items_missing_keys_or_wrong_types():
    raw = '[{"type":"PERSON","text":"A"},{"type":"PERSON"},{"text":"B"},{"type":1,"text":"C"}]'
    assert parse_items(raw) == [{"type": "PERSON", "text": "A"}]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/detectors/test_llm_parse.py -v`
Expected: FAIL — `ImportError: cannot import name 'parse_items'`

- [ ] **Step 3: Write implementation (append to `llm.py`)**

```python
import json as _json
import re as _re

_FENCE = _re.compile(r"^```(?:json)?\s*|\s*```$", _re.IGNORECASE)

def parse_items(raw: str) -> list[dict]:
    """Parse model output into a list of {'type': str, 'text': str}.

    Tolerant of code fences and surrounding prose; malformed output yields []."""
    if not raw or not raw.strip():
        return []
    cleaned = _FENCE.sub("", raw.strip())
    # fall back to the first [...] block if the model added prose
    if not cleaned.lstrip().startswith("["):
        m = _re.search(r"\[.*\]", cleaned, _re.DOTALL)
        cleaned = m.group(0) if m else cleaned
    try:
        data = _json.loads(cleaned)
    except ValueError:
        return []
    if not isinstance(data, list):
        return []
    out = []
    for it in data:
        if (isinstance(it, dict) and isinstance(it.get("type"), str)
                and isinstance(it.get("text"), str)):
            out.append({"type": it["type"], "text": it["text"]})
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/detectors/test_llm_parse.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/thickanon/detectors/llm.py tests/detectors/test_llm_parse.py
git commit -m "feat: tolerant parser for LLM JSON output"
```

---

### Task 4: Extract type normalization into a shared module

**Files:**
- Create: `src/thickanon/detectors/normalize.py`
- Modify: `src/thickanon/detectors/engine.py`
- Test: `tests/detectors/test_normalize.py`

Rationale: both `engine.py` and `llm.py` need the type→token normalization. Extracting it avoids a circular import (engine imports llm in Task 10).

- [ ] **Step 1: Write the failing test**

```python
# tests/detectors/test_normalize.py
from thickanon.detectors.normalize import normalize_type

def test_known_aliases():
    assert normalize_type("EMAIL_ADDRESS") == "EMAIL"
    assert normalize_type("IP_ADDRESS") == "IP"
    assert normalize_type("DENY") == "TERM"

def test_unknown_passthrough():
    assert normalize_type("PERSON") == "PERSON"

def test_spaces_and_case_normalized():
    assert normalize_type("Job Title") == "JOB_TITLE"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/detectors/test_normalize.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write implementation**

```python
# src/thickanon/detectors/normalize.py
_TYPE_NORMALIZE = {
    "EMAIL_ADDRESS": "EMAIL",
    "IP_ADDRESS": "IP",
    "IBAN_CODE": "IBAN",
    "PHONE_NUMBER": "PHONE",
    "DENY": "TERM",
}

def normalize_type(t: str) -> str:
    """Map a detector's raw entity type to the readable token vocabulary."""
    canonical = t.strip().upper().replace(" ", "_")
    return _TYPE_NORMALIZE.get(canonical, canonical)
```

Then in `engine.py`: delete the local `_TYPE_NORMALIZE` dict, add
`from thickanon.detectors.normalize import normalize_type` at the top, and in
`detect()` replace `_TYPE_NORMALIZE.get(r.entity_type, r.entity_type)` with
`normalize_type(r.entity_type)`.

- [ ] **Step 4: Run tests to verify they pass (including no regression)**

Run: `pytest tests/detectors/ -q`
Expected: PASS (new normalize tests + existing engine tests still green)

- [ ] **Step 5: Commit**

```bash
git add src/thickanon/detectors/normalize.py src/thickanon/detectors/engine.py tests/detectors/test_normalize.py
git commit -m "refactor: extract normalize_type into detectors/normalize.py"
```

---

### Task 5: Offset resolution (offset-via-search + hallucination drop)

**Files:**
- Modify: `src/thickanon/detectors/llm.py`
- Test: `tests/detectors/test_llm_resolve.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/detectors/test_llm_resolve.py
from thickanon.detectors.llm import resolve_spans

def test_found_span_gets_correct_offsets_and_confidence():
    text = "Hi John, regards Berlin office"
    ents = resolve_spans(text, [{"type": "PERSON", "text": "John"}], confidence=0.5)
    assert len(ents) == 1
    e = ents[0]
    assert text[e.start:e.end] == "John" and e.entity_type == "PERSON" and e.score == 0.5

def test_hallucinated_span_dropped():
    text = "no names here"
    assert resolve_spans(text, [{"type": "PERSON", "text": "Zorptron"}], 0.5) == []

def test_multiple_occurrences_all_returned():
    text = "John and John"
    ents = resolve_spans(text, [{"type": "PERSON", "text": "John"}], 0.5)
    assert sorted((e.start, e.end) for e in ents) == [(0, 4), (9, 13)]

def test_type_normalized_and_base_offset_applied():
    ents = resolve_spans("jane@x.com", [{"type": "email address", "text": "jane@x.com"}], 0.5, base=100)
    assert ents[0].entity_type == "EMAIL" and ents[0].start == 100 and ents[0].end == 110
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/detectors/test_llm_resolve.py -v`
Expected: FAIL — `ImportError: cannot import name 'resolve_spans'`

- [ ] **Step 3: Write implementation (append to `llm.py`)**

```python
from thickanon.core.types import Entity
from thickanon.detectors.normalize import normalize_type

def resolve_spans(text: str, items: list[dict], confidence: float, base: int = 0) -> list[Entity]:
    """Locate each item's verbatim 'text' in `text` and emit Entity spans.

    Items whose text does not occur verbatim are dropped (hallucinations).
    Every occurrence of a found substring becomes its own span. Offsets are
    shifted by `base` (used when `text` is a chunk of a larger fragment)."""
    out = []
    for it in items:
        needle = it["text"]
        if not needle:
            continue
        etype = normalize_type(it["type"])
        start = text.find(needle)
        while start != -1:
            out.append(Entity(base + start, base + start + len(needle), etype,
                              confidence, needle))
            start = text.find(needle, start + len(needle))
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/detectors/test_llm_resolve.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/thickanon/detectors/llm.py tests/detectors/test_llm_resolve.py
git commit -m "feat: offset-via-search span resolution with hallucination drop"
```

---

### Task 6: Chunking

**Files:**
- Modify: `src/thickanon/detectors/llm.py`
- Test: `tests/detectors/test_llm_chunk.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/detectors/test_llm_chunk.py
from thickanon.detectors.llm import iter_chunks

def test_short_text_single_chunk():
    assert iter_chunks("hello", max_chars=100) == [(0, "hello")]

def test_long_text_split_with_overlap_and_bases():
    text = "abcdefghij"  # 10 chars
    chunks = iter_chunks(text, max_chars=4, overlap=1)
    # each chunk must be reconstructable from its base
    for base, chunk in chunks:
        assert text[base:base + len(chunk)] == chunk
    # full coverage: every index appears in at least one chunk
    covered = set()
    for base, chunk in chunks:
        covered.update(range(base, base + len(chunk)))
    assert covered == set(range(len(text)))
    assert all(len(c) <= 4 for _, c in chunks)

def test_empty_text():
    assert iter_chunks("", max_chars=4) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/detectors/test_llm_chunk.py -v`
Expected: FAIL — `ImportError: cannot import name 'iter_chunks'`

- [ ] **Step 3: Write implementation (append to `llm.py`)**

```python
def iter_chunks(text: str, max_chars: int, overlap: int = 200) -> list[tuple[int, str]]:
    """Split text into overlapping windows of at most max_chars.

    Returns (base_offset, chunk_text) pairs covering the whole string. Overlap
    reduces the chance of splitting an entity across a boundary."""
    if not text:
        return []
    if len(text) <= max_chars:
        return [(0, text)]
    step = max(1, max_chars - overlap)
    chunks = []
    pos = 0
    while pos < len(text):
        chunks.append((pos, text[pos:pos + max_chars]))
        if pos + max_chars >= len(text):
            break
        pos += step
    return chunks
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/detectors/test_llm_chunk.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/thickanon/detectors/llm.py tests/detectors/test_llm_chunk.py
git commit -m "feat: overlapping chunker for long fragments"
```

---

### Task 7: llm_detect (end-to-end with a stub runner)

**Files:**
- Modify: `src/thickanon/detectors/llm.py`
- Test: `tests/detectors/test_llm_detect.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/detectors/test_llm_detect.py
from thickanon.core.types import LLMConfig
from thickanon.detectors.llm import llm_detect

def test_llm_detect_with_stub_runner():
    text = "Patient John Carter visited Berlin clinic"
    def runner(prompt):  # ignores prompt, returns canned JSON
        return '[{"type":"PERSON","text":"John Carter"},{"type":"LOCATION","text":"Berlin"}]'
    cfg = LLMConfig(enabled=True, confidence=0.5, categories=["PERSON", "LOCATION"])
    ents = llm_detect(text, cfg, runner=runner)
    by_type = {e.entity_type: e for e in ents}
    assert text[by_type["PERSON"].start:by_type["PERSON"].end] == "John Carter"
    assert by_type["LOCATION"].score == 0.5

def test_llm_detect_dedupes_across_chunks():
    text = "John " * 50  # long enough to chunk; overlaps would double-count
    def runner(prompt):
        return '[{"type":"PERSON","text":"John"}]'
    cfg = LLMConfig(enabled=True, max_chunk_chars=40)
    ents = llm_detect(text, cfg, runner=runner)
    spans = [(e.start, e.end) for e in ents]
    assert len(spans) == len(set(spans))  # no duplicate spans from overlap
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/detectors/test_llm_detect.py -v`
Expected: FAIL — `ImportError: cannot import name 'llm_detect'`

- [ ] **Step 3: Write implementation (append to `llm.py`)**

```python
from typing import Callable

def llm_detect(text: str, llm_config, runner: Callable[[str], str]) -> list[Entity]:
    """Run the model over (chunked) text and return resolved Entity spans.

    `runner` maps a prompt to raw model text; injected so tests need no model."""
    seen = set()
    out = []
    for base, chunk in iter_chunks(text, llm_config.max_chunk_chars):
        prompt = build_prompt(chunk, llm_config.categories, llm_config.custom_instruction)
        items = parse_items(runner(prompt))
        for e in resolve_spans(chunk, items, llm_config.confidence, base=base):
            key = (e.entity_type, e.start, e.end)
            if key not in seen:
                seen.add(key)
                out.append(e)
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/detectors/test_llm_detect.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/thickanon/detectors/llm.py tests/detectors/test_llm_detect.py
git commit -m "feat: llm_detect pipeline (prompt->runner->parse->resolve->dedup)"
```

---

### Task 8: Model acquisition (download + sha256 cache)

**Files:**
- Create: `src/thickanon/detectors/llm_model.py`
- Test: `tests/detectors/test_llm_model_cache.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/detectors/test_llm_model_cache.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/detectors/test_llm_model_cache.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write implementation**

```python
# src/thickanon/detectors/llm_model.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/detectors/test_llm_model_cache.py -v`
Expected: PASS

- [ ] **Step 5: (one-time, manual) pin the real sha256**

After implementation, the implementer should run the model once (Task 9 smoke or
`python -c "from thickanon.detectors.llm_model import ensure_model; from thickanon.core.types import LLMConfig; print(ensure_model(LLMConfig()))"`),
compute the sha256 of the downloaded file (`certutil -hashfile <path> SHA256` on
Windows), and paste it into `DEFAULT_LLM_SHA256` in `core/types.py`. Until pinned,
verification is skipped with a warning (empty sha256). Note this in the commit.

- [ ] **Step 6: Commit**

```bash
git add src/thickanon/detectors/llm_model.py tests/detectors/test_llm_model_cache.py
git commit -m "feat: GGUF model download + sha256-verified cache"
```

---

### Task 9: load_runner (build the llama.cpp inference callable)

**Files:**
- Modify: `src/thickanon/detectors/llm_model.py`
- Test: `tests/detectors/test_llm_runner.py`

`load_runner` builds a llama-cpp-python model and returns a `Callable[[str], str]`.
It cannot be exercised without the native lib + a model, so the unit test only
covers the error path (clear failure when llama_cpp is unavailable). Real inference
is covered by the gated integration test in Task 13.

- [ ] **Step 1: Write the failing test**

```python
# tests/detectors/test_llm_runner.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/detectors/test_llm_runner.py -v`
Expected: FAIL — `AttributeError: module ... has no attribute 'load_runner'`

- [ ] **Step 3: Write implementation (append to `llm_model.py`)**

```python
# GBNF grammar constraining output to a JSON array of {"type","text"} objects.
_JSON_GRAMMAR = r'''
root   ::= "[" ws (obj (ws "," ws obj)*)? ws "]"
obj    ::= "{" ws "\"type\"" ws ":" ws string ws "," ws "\"text\"" ws ":" ws string ws "}"
string ::= "\"" ([^"\\] | "\\" .)* "\""
ws     ::= [ \t\n]*
'''

def load_runner(llm_config):
    """Return a Callable[[str], str] that runs the local model on a prompt.

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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/detectors/test_llm_runner.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/thickanon/detectors/llm_model.py tests/detectors/test_llm_runner.py
git commit -m "feat: load_runner builds grammar-constrained llama.cpp callable"
```

---

### Task 10: Wire the LLM branch into engine.detect()

**Files:**
- Modify: `src/thickanon/detectors/engine.py`
- Test: `tests/detectors/test_engine_llm.py`

When `config.llm` is enabled, run custom regex + deny-list directly (no spaCy/
AnalyzerEngine) plus the LLM, and merge through the existing overlap resolver.

- [ ] **Step 1: Write the failing test**

```python
# tests/detectors/test_engine_llm.py
from thickanon.core.types import AnonymizeConfig, LLMConfig
from thickanon.detectors import llm_model
from thickanon.detectors.engine import detect

def test_llm_branch_merges_regex_and_llm(monkeypatch):
    # stub load_runner so no real model is needed
    def fake_runner(prompt):
        return '[{"type":"PERSON","text":"John Carter"}]'
    monkeypatch.setattr(llm_model, "load_runner", lambda cfg: fake_runner)

    text = "John Carter emailed jane@acme.com from 10.0.0.5"
    cfg = AnonymizeConfig(llm=LLMConfig(enabled=True), low_threshold=0.35)
    ents = detect(text, cfg)
    labels = {e.entity_type for e in ents}
    assert {"PERSON", "EMAIL", "IP"} <= labels       # regex + LLM both present
    for e in ents:
        assert text[e.start:e.end] == e.text          # offsets valid

def test_llm_disabled_uses_spacy_path():
    # llm None -> existing behavior unchanged
    ents = detect("John at 10.0.0.1", AnonymizeConfig())
    assert {"IP"} <= {e.entity_type for e in ents}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/detectors/test_engine_llm.py -v`
Expected: FAIL — LLM branch not implemented (PERSON missing or error)

- [ ] **Step 3: Write implementation (modify `engine.py`)**

Add imports at top:

```python
from thickanon.detectors.recognizers import custom_recognizers, deny_list_recognizer
from thickanon.detectors import llm_model
from thickanon.detectors.llm import llm_detect
from thickanon.core.types import Entity  # if not already imported
```

Add a helper:

```python
def _regex_denylist_entities(text: str, config) -> list[Entity]:
    """Run custom regex recognizers + deny-list directly (no spaCy NLP)."""
    results = []
    for rec in custom_recognizers():
        results += rec.analyze(text, rec.supported_entities, None)
    if config.deny_list:
        dl = deny_list_recognizer(config.deny_list)
        results += dl.analyze(text, ["DENY"], None)
    return [Entity(r.start, r.end, normalize_type(r.entity_type), r.score,
                   text[r.start:r.end]) for r in results]
```

Rewrite the body of `detect()` so it builds a unified `Entity` list, then resolves:

```python
def detect(text: str, config: AnonymizeConfig) -> list[Entity]:
    if config.llm is not None and config.llm.enabled:
        entities = _regex_denylist_entities(text, config)
        runner = llm_model.load_runner(config.llm)
        entities += llm_detect(text, config.llm, runner)
    else:
        analyzer = _base_analyzer(config.language)
        ad_hoc = [deny_list_recognizer(config.deny_list)] if config.deny_list else []
        raw = analyzer.analyze(text=text, language=config.language, ad_hoc_recognizers=ad_hoc)
        entities = [Entity(r.start, r.end, normalize_type(r.entity_type), r.score,
                           text[r.start:r.end]) for r in raw]
    entities = [e for e in entities if e.score >= config.low_threshold]
    return _resolve_overlaps(entities)
```

Note: `_resolve_overlaps` already operates on objects with `.score/.start/.end`, so it
works unchanged on `Entity`. It now returns `Entity` objects directly — the old
post-resolve `Entity` construction is removed (folded in above). Run the FULL suite to
confirm the non-LLM path is byte-for-byte unchanged.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/detectors/ tests/core/ -q`
Expected: PASS (new LLM-branch tests + all existing detector/engine/orchestrator tests)

- [ ] **Step 5: Commit**

```bash
git add src/thickanon/detectors/engine.py tests/detectors/test_engine_llm.py
git commit -m "feat: engine LLM branch (regex+denylist+LLM, no spaCy when enabled)"
```

---

### Task 11: CLI flags + download-model command

**Files:**
- Modify: `src/thickanon/cli.py`
- Test: `tests/test_cli_llm.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli_llm.py
from thickanon.cli import main
from thickanon.detectors import llm_model

def test_cli_llm_flag_runs_with_stub(tmp_path, monkeypatch):
    monkeypatch.setattr(llm_model, "load_runner",
                        lambda cfg: (lambda prompt: '[{"type":"PERSON","text":"John Carter"}]'))
    root = tmp_path / "data"; root.mkdir()
    f = root / "x.txt"; f.write_text("John Carter pinged 10.0.0.7", encoding="utf-8")
    mp = tmp_path / "map.json"
    rc = main(["anon", str(f), "--root", str(root), "--mapping", str(mp),
               "--mode", "auto_redact", "--llm", "--llm-instruction", "be thorough"])
    assert rc == 0
    out = f.read_text(encoding="utf-8")
    assert "John Carter" not in out and "10.0.0.7" not in out

def test_cli_download_model_invokes_ensure(tmp_path, monkeypatch, capsys):
    called = {}
    monkeypatch.setattr(llm_model, "ensure_model",
                        lambda cfg: called.setdefault("path", "/fake/m.gguf") or "/fake/m.gguf")
    rc = main(["download-model"])
    assert rc == 0 and called["path"] == "/fake/m.gguf"
    assert "/fake/m.gguf" in capsys.readouterr().out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli_llm.py -v`
Expected: FAIL — unrecognized arguments / no `download-model`

- [ ] **Step 3: Write implementation (modify `cli.py`)**

Add LLM options to the `anonymize` subparser (after `--passphrase`):

```python
    a.add_argument("--llm", action="store_true", help="use the local LLM detector")
    a.add_argument("--llm-model", help="path to a GGUF model file")
    a.add_argument("--llm-gpu-layers", type=int, default=0)
    a.add_argument("--llm-instruction", default="")
```

Add a `download-model` subparser:

```python
    dl = sub.add_parser("download-model")
    dl.set_defaults(action="download-model")
    dl.add_argument("--llm-model", help="path to store the GGUF model file")
```

In the dispatch, build the `LLMConfig` when `--llm` is set, and handle the new command.
Add the import `from thickanon.core.types import LLMConfig` and
`from thickanon.detectors import llm_model` at the top. In the `anonymize` branch,
construct the config:

```python
        llm_cfg = None
        if ns.llm:
            llm_cfg = LLMConfig(enabled=True, model_path=ns.llm_model,
                                n_gpu_layers=ns.llm_gpu_layers,
                                custom_instruction=ns.llm_instruction)
        cfg = AnonymizeConfig(mode=ReviewMode(ns.mode), deny_list=ns.deny, llm=llm_cfg)
```

(replace the existing `cfg = AnonymizeConfig(...)` line). Add the command handler before
the final `deanonymize` fallthrough:

```python
    if ns.action == "download-model":
        path = llm_model.ensure_model(LLMConfig(model_path=getattr(ns, "llm_model", None)))
        print(f"Model ready at: {path}")
        return 0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_cli_llm.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/thickanon/cli.py tests/test_cli_llm.py
git commit -m "feat: CLI --llm flags and download-model command"
```

---

### Task 12: UI wiring (toggle, instruction, gpu layers, download)

**Files:**
- Modify: `src/thickanon/ui/api.py`
- Modify: `src/thickanon/ui/web/index.html`
- Test: `tests/ui/test_api_llm.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/ui/test_api_llm.py
from thickanon.ui.api import Api
from thickanon.detectors import llm_model

def test_api_anonymize_with_llm(tmp_path, monkeypatch):
    monkeypatch.setattr(llm_model, "load_runner",
                        lambda cfg: (lambda prompt: '[{"type":"PERSON","text":"John Carter"}]'))
    root = tmp_path / "data"; root.mkdir()
    f = root / "n.txt"; f.write_text("John Carter at 10.0.0.3", encoding="utf-8")
    api = Api()
    res = api.anonymize(files=[str(f)], root=str(root), mapping_path=str(tmp_path / "m.json"),
                        mode="auto_redact", deny=[], backup_dir=None, passphrase=None,
                        llm=True, llm_instruction="thorough", llm_gpu_layers=0)
    assert res["ok"] is True
    assert "John Carter" not in f.read_text(encoding="utf-8")

def test_api_download_model(monkeypatch):
    monkeypatch.setattr(llm_model, "ensure_model", lambda cfg: "/fake/m.gguf")
    res = Api().download_model()
    assert res["ok"] is True and res["path"] == "/fake/m.gguf"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/ui/test_api_llm.py -v`
Expected: FAIL — `anonymize() got an unexpected keyword argument 'llm'`

- [ ] **Step 3: Write implementation (modify `ui/api.py`)**

Add imports: `from thickanon.core.types import LLMConfig` and
`from thickanon.detectors import llm_model`. Change the `anonymize` signature and body
to accept the LLM args (keyword, with defaults so existing calls/tests keep working):

```python
    def anonymize(self, files, root, mapping_path, mode, deny, backup_dir, passphrase,
                  llm=False, llm_instruction="", llm_gpu_layers=0):
        try:
            # ... existing root inference + default-mapping + ensure_mapping_outside_root ...
            llm_cfg = LLMConfig(enabled=True, custom_instruction=llm_instruction,
                                n_gpu_layers=llm_gpu_layers) if llm else None
            cfg = AnonymizeConfig(mode=ReviewMode(mode), deny_list=deny or [], llm=llm_cfg)
            # ... rest unchanged (anonymize_paths(... cfg ...), mapping.save, return) ...
```

(Keep every existing line in the method; only add the three params, the `llm_cfg`
line, and pass `llm=llm_cfg` into the `AnonymizeConfig(...)`.) Add a method:

```python
    def download_model(self):
        try:
            path = llm_model.ensure_model(LLMConfig())
            return {"ok": True, "path": str(path)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
```

In `index.html`, add inside the form (after the passphrase field):

```html
 <label><input type="checkbox" id="llm"> Use local LLM (higher recall, slower)</label>
 <div class="row">
   <div><label>LLM instruction (optional)</label><input id="llm_instr" placeholder="what counts as sensitive here"></div>
   <div><label>GPU layers (0 = CPU)</label><input id="llm_gpu" type="number" value="0"></div>
 </div>
 <button class="ghost" onclick="downloadModel()">Download LLM model</button>
```

And update the anonymize call + add the handler in the `<script>`:

```javascript
 // inside run('anonymize'), extend the api.anonymize(...) call with:
 //   , $('llm').checked, $('llm_instr').value, parseInt($('llm_gpu').value)||0
 async function downloadModel(){
   const out = $('out'); out.textContent = 'Downloading model…';
   const res = await window.pywebview.api.download_model();
   out.textContent = res.ok ? ('Model ready: ' + res.path) : ('Error: ' + res.error);
 }
```

(Extend the existing `window.pywebview.api.anonymize(...)` argument list with the three
new trailing arguments shown above.)

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/ui/test_api_llm.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/thickanon/ui/api.py src/thickanon/ui/web/index.html tests/ui/test_api_llm.py
git commit -m "feat: UI LLM toggle, instruction, gpu layers, download button"
```

---

### Task 13: Build config, dependency, and gated integration test

**Files:**
- Modify: `pyproject.toml`
- Modify: `packaging/thickanon.spec`
- Modify: `README.md`
- Test: `tests/integration/test_llm_real.py`
- Create: `tests/integration/__init__.py`

- [ ] **Step 1: Add the dependency**

In `pyproject.toml`, add `"llama-cpp-python"` to `dependencies`. Install it:

Run: `pip install -e ".[dev]"`
Expected: llama-cpp-python builds/installs (CPU wheel).

- [ ] **Step 2: Write the gated integration test**

```python
# tests/integration/test_llm_real.py
import os, pytest
from thickanon.core.types import AnonymizeConfig, LLMConfig
from thickanon.detectors.engine import detect

pytestmark = pytest.mark.skipif(
    os.environ.get("THICKANON_LLM_IT") != "1",
    reason="set THICKANON_LLM_IT=1 to run the real-model integration test",
)

def test_real_model_detects_name():
    cfg = AnonymizeConfig(llm=LLMConfig(enabled=True))  # downloads default model
    ents = detect("Please contact Dr. Eleanor Whitfield about the case.", cfg)
    assert any(e.entity_type == "PERSON" and "Whitfield" in e.text for e in ents)
```

`tests/integration/__init__.py` is empty.

- [ ] **Step 3: Verify the gated test is skipped by default**

Run: `pytest tests/integration/test_llm_real.py -v`
Expected: SKIPPED (1 skipped)

- [ ] **Step 4: Update the PyInstaller spec to bundle llama_cpp**

In `packaging/thickanon.spec`, add `llama_cpp` collection (after the existing
`collect_all` loop) and ensure it is NOT excluded:

```python
for pkg in ["llama_cpp"]:
    d, b, h = collect_all(pkg)
    datas += d; binaries += b; hiddenimports += h
```

`_EXCLUDES` must not contain `llama_cpp` (it doesn't — leave torch etc. as-is). The
default build stays CPU-only; a CUDA-enabled `llama-cpp-python` would be installed in a
separate environment to produce a GPU build flavor (documented, not built here).

- [ ] **Step 5: Update README**

Add a "Local LLM detection (optional)" section documenting: enabling via `--llm` /
the UI toggle; first-run model download (`download-model`); that the model loads once
per process (pass a folder, don't loop per-file); GPU via `--llm-gpu-layers` needs a
CUDA llama.cpp build; and that LLM hits are gray-band (reviewed in quick_review). Also
note enabled-but-unloadable is a hard error.

- [ ] **Step 6: Run the full suite**

Run: `pytest -q`
Expected: PASS (all prior tests + new LLM unit tests; integration test skipped)

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml packaging/thickanon.spec README.md tests/integration
git commit -m "build: add llama-cpp-python, bundle in spec, gated LLM integration test, docs"
```

---

## Self-review notes

- **Spec coverage:** runtime=llama-cpp-python (T9, T13), first-run download+sha256 (T8),
  LLM-replaces-spaCy with regex+denylist always (T10), configurable categories+instruction
  (T1, T2, T11, T12), GBNF+temp0 (T9), offset-via-search + hallucination drop (T5),
  gray-band fixed confidence (T1, T5, T7), smaller default model + GPU offload config
  (T1, T9, T11, T12), off-by-default + hard-error-when-unloadable (T1, T9, T10), chunking
  (T6), CLI + UI surface (T11, T12), build/bundle + gated IT (T13), README (T13). All spec
  sections map to a task.
- **Placeholder scan:** the only deferred concrete value is `DEFAULT_LLM_SHA256` (an
  external artifact hash), handled explicitly by Task 8 Step 5 with a procedure to pin it;
  empty meanwhile means "skip verification with a warning," which is implemented, not a TODO.
- **Type consistency:** `LLMConfig` fields (`enabled`, `model_path`, `model_url`, `sha256`,
  `n_gpu_layers`, `confidence`, `categories`, `custom_instruction`, `max_chunk_chars`),
  `normalize_type`, `resolve_spans(text, items, confidence, base)`, `iter_chunks(text,
  max_chars, overlap)`, `llm_detect(text, llm_config, runner)`, `ensure_model`,
  `load_runner` are used identically across tasks. `_resolve_overlaps` is reused on `Entity`
  objects (duck-typed on start/end/score).
- **Known limitation carried forward:** entities split across chunk boundaries rely on the
  overlap window; very long single entities beyond the overlap could still be missed
  (residual scan remains the backstop).

# GLiNER-PII Detector — Design

**Date:** 2026-06-02
**Status:** Approved design, pending spec review
**Supersedes:** the on-device generative-LLM backend
(`docs/superpowers/specs/2026-06-01-llm-detector-design.md`). That backend (llama.cpp +
GGUF instruct model) is **removed** and replaced by this one.

## 1. Purpose

Replace the optional generative-LLM detector with a purpose-built **GLiNER neural NER
detector** running via **`fast_gliner`** (a Rust/ONNX inference engine — torch-free, with
prebuilt CPU wheels). GLiNER is a small bidirectional encoder built for zero-shot,
label-configurable entity extraction; for PII it is more accurate, faster on CPU, and
smaller than a general instruct LLM, and it returns exact character offsets and real
confidence scores natively.

The feature stays **optional and off by default**. When enabled it **replaces the spaCy
NER layer**; the regex and deny-list layers always run.

## 2. Why this replaces the LLM backend (rationale)

Research (June 2026) showed GLiNER-PII outperforms general LLMs at zero-shot PII NER while
using far less compute, and that `fast_gliner` provides it torch-free via ONNX with native
offsets and scores. Concretely, GLiNER returns `{label, text, start, end, score}` per span,
so the entire machinery the LLM backend needed to coax and clean structured output —
prompt builder, JSON parser, GBNF grammar, offset-via-search, hallucination drop, fixed
gray-band score — is **deleted**. The result is a smaller, faster, more accurate, and
simpler detector.

## 3. Goals & non-goals

**Goals**
- Higher-recall, higher-precision PII/sensitive-entity detection than spaCy NER.
- Fully local; torch-free; small (`fast_gliner` CPU wheel + ONNX model, no GGUF).
- Reuse the existing `Entity` pipeline unchanged (tokens, mapping, reversibility,
  residual scan, review bands).
- Real per-entity confidence flows through the existing thresholds/bands.

**Non-goals**
- Generative / prose-instruction detection (GLiNER is label-driven). The `custom_instruction`
  concept is dropped.
- Keeping the llama.cpp backend (removed; not a dual-backend design).
- A persistent server/daemon (model is cached per process; GUI keeps it warm per session).

## 4. What is removed

- `src/thickanon/detectors/llm.py` and its tests (`test_llm_prompt.py`, `test_llm_parse.py`,
  `test_llm_resolve.py`, `test_llm_chunk.py`, `test_llm_detect.py`).
- `src/thickanon/detectors/llm_model.py` and its tests (`test_llm_model_cache.py`,
  `test_llm_runner.py`).
- `tests/integration/test_llm_real.py`.
- `LLMConfig` / `DEFAULT_LLM_*` in `core/types.py` and `AnonymizeConfig.llm`.
- the `llama-cpp-python` `[llm]` extra and its guarded bundling in the PyInstaller spec.
- LLM tests in `test_cli_llm.py` / `test_api_llm.py`.

The shared `detectors/normalize.py` (extracted during the LLM work) is **kept** — both the
spaCy path and the GLiNER path use `normalize_type`.

## 5. Architecture

Same detection seam as before; the neural detector is smaller.

```
detect(text, config):
    custom regex recognizers   ── always (IP / email / card / IBAN)
    deny-list                  ── always (when config.deny_list non-empty)
    if config.gliner and config.gliner.enabled:
        gliner_detect(text, config.gliner, model)   ── neural NER (regex+denylist, NO spaCy)
    else:
        spaCy NER via Presidio AnalyzerEngine         ── current default
    → merge all spans → _resolve_overlaps → list[Entity]   (unchanged)
```

New modules:
- **`src/thickanon/detectors/gliner.py`** — `gliner_detect(text, cfg, model) -> list[Entity]`.
  Chunks long text, calls `model.predict_entities(chunk, cfg.labels, threshold=cfg.threshold)`,
  shifts offsets by the chunk base, maps `label` through `normalize_type`, keeps the GLiNER
  `score`, de-duplicates by `(type, start, end)`. `model` is injected so unit tests use a stub.
- **`src/thickanon/detectors/gliner_model.py`** — `load_model(cfg) -> object` builds/loads the
  fast_gliner model (cached per process via a module-level cache keyed on `(model_id,
  model_path, gpu)`); first use downloads the ONNX model from Hugging Face into the cache.
  Raises a clear `RuntimeError` if `fast_gliner` is not installed.
- **`engine.detect()`** — the LLM branch becomes the GLiNER branch: when enabled, build
  regex + deny-list Entities directly (no spaCy), obtain the model via
  `gliner_model.load_model(config.gliner)` (module-referenced so tests monkeypatch it), append
  `gliner_detect(...)`, filter by `low_threshold`, `_resolve_overlaps`. Disabled path
  unchanged.

## 6. Confidence and review bands (real scores)

GLiNER returns a real `score` in [0,1] per entity. We set `Entity.score = score`, so it flows
through the existing `low_threshold` / `high_threshold` bands and `partition()` exactly like
regex/spaCy hits: high-confidence auto-applies, gray-band goes to review (`quick_review`) or
is applied (`auto_redact`) or skipped (`auto_skip`). `GLiNERConfig.threshold` is the minimum
score GLiNER emits at all (entities below it are never produced). This replaces the LLM's
fixed-0.5 gray-band hack.

## 7. Config (`GLiNERConfig`, replaces `LLMConfig`)

`AnonymizeConfig.llm` is removed; `AnonymizeConfig.gliner: GLiNERConfig | None = None` is added.

| field | default | meaning |
|---|---|---|
| `enabled` | `False` | opt-in master switch |
| `model_id` | a pinned ONNX GLiNER PII model on HF | which model to load |
| `model_path` | `None` | explicit local model dir; else library/HF cache |
| `labels` | default sensitive-entity label list | entity labels to detect |
| `threshold` | `0.5` | minimum GLiNER score to emit |
| `gpu` | `False` | use CUDA (requires the `fast_gliner[cuda]` wheel) |
| `max_chunk_chars` | `4000` | chunk size for long fragments |

Default `labels` (GLiNER labels, lowercase natural phrases): `person`, `organization`,
`location`, `email`, `phone number`, `address`, `date of birth`, `job title`,
`account number`, `id number`. The implementer pins `model_id` to a concrete ONNX GLiNER
model that `fast_gliner` supports (e.g. an `onnx-community` GLiNER v2.1 or a GLiNER PII ONNX
export) and verifies it loads.

- **CLI**: `--gliner` enables it; `--gliner-labels a,b,c`, `--gliner-threshold 0.5`,
  `--gliner-gpu`, `--gliner-model PATH`. A `download-model` command pre-fetches the model.
- **UI**: a "Use neural NER (GLiNER)" toggle, an editable labels field, a threshold input, a
  GPU checkbox, and a one-time "Download model" button. The toggle keeps the model warm for
  the session.

## 8. Model acquisition

`fast_gliner` loads ONNX GLiNER models from Hugging Face. `load_model` pins a default
`model_id` and lets the library download/cache it on first use (HF cache, or
`~/.thickanon/models/` if we pass an explicit `model_path`); `download-model` triggers the
fetch ahead of time. No custom sha256/download code — the library and HF hub handle
retrieval and integrity. A download/load failure is a hard error.

## 9. Error handling

- `enabled=True` but `fast_gliner` missing or model load fails → **hard error**, run stops
  (no silent fallback to weaker detection).
- A chunk returning no entities → no hits for that chunk; regex + deny-list still apply.
- Defensive invariant: every emitted `Entity` satisfies `text[start:end] == entity.text`
  (GLiNER gives exact offsets; we assert/skip any span that fails this, guarding against a
  model/encoding edge case).

## 10. Testing strategy

- **Unit (no model, fast)** with a stub `model` whose `predict_entities(text, labels,
  threshold=...)` returns canned `[{label,text,start,end,score}]`:
  - offset shifting across chunks + dedup by `(type, start, end)`.
  - label→token normalization (`"phone number"` → `[PHONE_NUMBER_1]` etc.).
  - threshold filtering (entities below `threshold` excluded — verify the detector passes
    `threshold` through and/or filters).
  - the defensive offset-mismatch skip.
  - `engine.detect()` GLiNER branch: merges regex + GLiNER, spaCy not loaded; scores
    preserved so bands work.
  - `gliner_model.load_model` raises a clear `RuntimeError` when `fast_gliner` is absent
    (monkeypatch the import), and caches the model per config key.
- **Gated integration**: `THICKANON_GLINER_IT=1` loads the real fast_gliner model and asserts
  a known name is detected and round-trips; skipped by default.
- **Build**: add `fast_gliner` as an optional extra `[gliner]`; remove the `llm` extra;
  guarded bundling of `fast_gliner` (+ its ONNX runtime native libs) in `packaging/thickanon.spec`;
  confirm the base suite passes without the extra installed.

## 11. Tech stack changes

- Add: `fast_gliner` (optional extra `[gliner]`; Rust/ONNX, prebuilt CPU wheel, no torch).
- Remove: `llama-cpp-python` (`[llm]` extra).
- Keep: stdlib only in the base install; Presidio/regex/spaCy default path unchanged.
- Default model: a pinned ONNX GLiNER PII model (`model_id`), downloaded on first use.

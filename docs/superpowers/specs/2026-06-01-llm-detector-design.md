# On-device LLM Detector — Design

**Date:** 2026-06-01
**Status:** Approved design, pending spec review
**Builds on:** thickAnonymizer v0.1 (`docs/superpowers/specs/2026-05-29-thickanonymizer-design.md`)

## 1. Purpose

Add an **optional** detection layer that runs a **local GGUF model** (via
llama-cpp-python) to catch context-dependent sensitive data the regex and small-NER
layers miss — names in unusual contexts, organizations, locations, and
user-configurable categories of confidential information. Everything stays on the
machine (the whole point: a local model scrubbing data before it goes to a cloud model).

The feature is **off by default** — pure opt-in. When enabled, the LLM **replaces the
spaCy NER layer**; the regex and deny-list layers always run regardless.

## 2. Goals & non-goals

**Goals**
- Higher recall on free-text / context-dependent sensitive data than spaCy NER.
- Fully local, offline after a one-time model download.
- Reuse the existing `Entity` pipeline unchanged (tokens, mapping, reversibility,
  residual scan, review modes).
- Reliable structured output (no hallucinated spans reaching the file).
- Reasonable performance: model loads once per process; GPU offload for speed.

**Non-goals**
- Replacing the regex layer (LLMs are unreliable on exact IP/card/IBAN — regex wins).
- A persistent model server / daemon (considered and deferred; the GUI keeps the model
  warm per session and a single CLI batch call loads it once, which covers the common
  cases).
- Bundling model weights inside the exe (they are downloaded to a cache).
- Cloud / remote inference of any kind.

## 3. Architecture

One new detector; nothing downstream changes.

```
detect(text, config):
    custom regex recognizers   ── always (IP / email / card / IBAN)
    deny-list                  ── always (when config.deny_list non-empty)
    if config.llm.enabled:
        LLMRecognizer.detect(text, config.llm)   ── names/orgs/locations/configured categories
    else:
        spaCy NER via Presidio AnalyzerEngine     ── current default
    → merge all spans → _resolve_overlaps → list[Entity]   (unchanged)
```

- New module **`src/thickanon/detectors/llm.py`** — model handle, prompt building,
  GBNF-constrained JSON generation, parsing, offset resolution, chunking. Exposes
  `llm_detect(text, llm_config, *, runner=None) -> list[Entity]`. The optional `runner`
  parameter injects the raw model call so tests run without a model.
- New module **`src/thickanon/detectors/llm_model.py`** — model cache resolution and
  first-run download + sha256 verification. Exposes `ensure_model(llm_config) -> Path`
  and `load_runner(llm_config) -> Callable[[str], str]` (builds the llama-cpp model and
  returns a callable that takes a prompt and returns raw model text).
- **`engine.detect()`** gains the `if config.llm.enabled` branch. When LLM mode is on it
  builds the analyzer from custom regex + deny-list only (no spaCy NLP engine loaded),
  then appends `llm_detect(...)` results before overlap resolution. When off, behavior is
  byte-for-byte today's behavior.

Each unit is independently testable: detection logic (with a stub runner), model
acquisition (with a temp cache + fake URL), and the engine branch.

## 4. The LLM detector (`llm.py`)

- **Prompt**: assembled from `llm_config.categories` (default list) plus an optional
  `custom_instruction`. Instructs the model to return every sensitive span **verbatim**
  with its category, and nothing else.
- **Guaranteed-valid output**: a **GBNF grammar** constrains generation to a JSON array of
  `{"type": <category>, "text": <string>}`. `temperature = 0` for determinism.
- **Offset-via-search (anti-hallucination)**: the model returns the type + the verbatim
  substring, never offsets. `llm_detect` then locates each returned `text` in the source
  fragment (all non-overlapping occurrences) to compute real `(start, end)`. **A returned
  string that does not appear in the fragment is dropped** — this is how hallucinations are
  filtered. Every emitted `Entity.text` therefore equals `fragment[start:end]` (the same
  invariant the rest of the pipeline relies on).
- **Scoring**: each LLM hit is assigned the fixed score `llm_config.confidence`
  (default `0.5` → gray band, so `quick_review` reviews them, `auto_redact` applies them,
  `auto_skip` drops them).
- **Type → token**: category names are normalized (uppercased, spaces→`_`) and flow through
  the existing `_TYPE_NORMALIZE` path, producing tokens like `[PERSON_1]`, `[ORG_1]`,
  `[SECRET_1]`.
- **Chunking**: fragments longer than `llm_config.max_chunk_chars` are split into
  overlapping windows so each fits the model context; results are merged and de-duplicated
  by `(type, start, end)`.

## 5. Model acquisition (`llm_model.py`)

- Models live in `~/.thickanon/models/` (overridable via `llm_config.model_path`).
- On first LLM run (or an explicit `download-model` action): download the GGUF from
  `llm_config.model_url` to the cache, **verify sha256** against `llm_config.sha256`, and
  load. Subsequent runs load from cache — fully offline.
- A download failure or checksum mismatch is a hard error; a corrupt model never loads.

## 6. Default model & performance

- **Default model: a ~1.5B instruct GGUF** (e.g. `qwen2.5-1.5b-instruct-q4`) for fast
  cold-load and inference. Users may opt up to a 3B model (higher recall) via config.
- **GPU offload**: `llm_config.n_gpu_layers` (default `0` = CPU). Offloading layers to a
  GPU gives ~10–50× speedup. GPU requires a **CUDA-enabled llama.cpp** — see §9 (a separate
  build flavor); the default build is CPU-only and runs everywhere.
- **Model loads once per process**, not per file. A single CLI batch call (`anon <folder>`)
  and the GUI session both load the model once and reuse it across all files/fragments.
  Looping the exe once-per-file pays the cold start each time — documented as an
  anti-pattern; pass a folder instead.
- Rough CPU ballparks (1.5B Q4): cold start ~5–12 s; ~3–15 s per fragment. GPU: sub-second
  to ~2 s per fragment.

## 7. Config surface

`AnonymizeConfig` gains an optional `llm: LLMConfig` (a dataclass):

| field | default | meaning |
|---|---|---|
| `enabled` | `False` | master switch (opt-in) |
| `model_path` | `None` | explicit GGUF path; else cache dir |
| `model_url` | pinned URL | where to download the default GGUF |
| `sha256` | pinned hash | integrity check for the download |
| `n_gpu_layers` | `0` | layers to offload to GPU (0 = CPU) |
| `confidence` | `0.5` | fixed score for LLM hits (gray band) |
| `categories` | default list | category names the prompt targets |
| `custom_instruction` | `""` | extra "what counts as sensitive here" text |
| `max_chunk_chars` | e.g. `4000` | chunk size for long fragments |

- **CLI**: `--llm` enables it; `--llm-model PATH`, `--llm-gpu-layers N`,
  `--llm-instruction TEXT`. A `download-model` subcommand pre-fetches the GGUF.
- **UI**: a "Use local LLM" toggle, an instruction textarea, a GPU-layers field, and a
  one-time "Download model" button with progress; the toggle keeps the model warm for the
  session.

## 8. Error handling

- `enabled=True` but llama-cpp-python missing or the model fails to load → **hard error**,
  the run stops. A privacy tool must not silently fall back to weaker detection without
  telling the user.
- Malformed/empty model output for a fragment → treated as "no LLM hits" for that fragment
  (regex + deny-list still apply), logged.
- Hallucinated spans (text not found in the fragment) → silently dropped (expected path,
  not an error).
- Download/checksum failure → hard error with a clear message.

## 9. Build implications

- Add `llama-cpp-python` as a dependency (CPU wheel by default; tens of MB — the exe stays
  ~600 MB since weights are downloaded, not bundled).
- PyInstaller must bundle the llama_cpp native library: add `collect_all("llama_cpp")` (or
  `collect_dynamic_libs`) to the spec; do **not** add `llama_cpp` to `_EXCLUDES`.
- **GPU build flavor**: a CUDA-enabled `llama-cpp-python` produces a larger, Nvidia-only
  exe. Plan for an optional second build (`thickanon-cuda.spec`) or documented install
  step; the default ships CPU-only. (We previously excluded the *torch* CUDA stack; llama.cpp
  uses its own CUDA build, independent of torch.)

## 10. Testing strategy

- **Unit (no model, fast)** with a stub `runner` callable returning canned JSON:
  - offset resolution: verbatim-found → correct offsets; not-found → dropped;
    multiple occurrences → multiple spans.
  - GBNF/JSON parsing of well-formed and malformed output.
  - chunk splitting + dedup by `(type, start, end)`.
  - type→token normalization (`"Job Title"` → `[JOB_TITLE_1]`).
  - prompt assembly from `categories` + `custom_instruction`.
  - `engine.detect()` LLM branch (inject stub) merges + overlap-resolves with regex.
  - `enabled` but runner load fails → raises (hard error).
- **Model acquisition** with a temp cache + a local file URL: download, checksum pass,
  checksum-mismatch failure.
- **Integration (gated)**: one end-to-end test behind an env flag / `skipif` that loads a
  real small GGUF if present and asserts a known name is detected and round-trips. Skipped
  in normal runs/CI.

## 11. Tech stack additions

- `llama-cpp-python` (GGUF inference, GBNF grammar)
- stdlib `urllib` + `hashlib` for download + sha256 (no new dep)
- Default model: a ~1.5B instruct GGUF (CPU-friendly), pinned URL + sha256

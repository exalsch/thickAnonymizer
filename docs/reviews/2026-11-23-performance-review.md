# thickanon - performance review

Date: 23.11.2026. Reviewer: a Claude Code subagent. No repository file was changed during the review.

## How it was measured

- Machine: i7-13800H (6 P-cores + 8 E-cores), 64 GB RAM, Python 3.13.11, presidio 2.2.364, spaCy 3.8.15, en_core_web_lg 3.8.0.
- Noise: other jobs ran on the machine at the same time. Unpinned timings varied by a factor of 2 to 4, so throughput numbers come from processes pinned to one P-core (`start /affinity 4`), and A/B tests ran each variant in turn inside one process. Exe start-up numbers are ranges.
- Exe emulation: torch and transformers made unimportable, the same as `_EXCLUDES` in the spec.
- Corpus (deterministic generator): 31 files, 541 KB on disk, 666.350 characters, 9.635 fragments. 20 mails of 2 KB, 6 Markdown files of 20 KB, 2 logs of 100 KB, 1 docx (421 paragraphs and table cells), 1 xlsx (9.006 string cells), 1 pptx (180 paragraphs). Mixed English and German. The current code finds 22.890 entities.
- "Identical" means the sorted entity list (file, fragment, start, end, type, score, text, band) is byte-identical to the current code.
- Prototypes and raw results were kept in the session scratchpad only.

## Baseline (MEASURED, one P-core, current code)

| Type | Time | Characters | Fragments | Throughput |
|---|---:|---:|---:|---:|
| .xlsx | 97.551 ms | 237.580 | 9.006 | 2,4 KB/s |
| .log | 16.284 ms | 200.292 | 2 | 12,0 KB/s |
| .md | 9.995 ms | 120.664 | 6 | 11,8 KB/s |
| .docx | 7.081 ms | 51.099 | 421 | 7,0 KB/s |
| .txt | 3.402 ms | 43.461 | 20 | 12,5 KB/s |
| .pptx | 2.560 ms | 13.254 | 180 | 5,1 KB/s |
| **Total** | **136.874 ms** | 666.350 | 9.635 | **4,8 KB/s** |

cProfile of the full scan: spaCy `nlp()` is 67 % of `analyze` (tok2vec alone 132,5 s of 517,0 s). The cost is per call, not per character: 9.717 calls, most on xlsx cells of 10 to 60 characters. PhoneRecognizer 15 % (it runs once for each of 8 regions), other pattern recognizers 7 %, context enhancement 7 % (of which a Presidio `deepcopy` is 23,6 s). Small fragments are 3 to 5 times slower per character than plain text.

## Findings, ranked by expected gain

### 1. Send all windows of a file through `nlp.pipe` in one batch

- Where: `core/plan.py:178-188` calls `detect()` per fragment; `detectors/engine.py:93-105` runs `nlp(text)` on one text at a time.
- Gain (MEASURED, pinned): 136.874 ms -> 62.560 ms in total, **x2,19**. xlsx x3,0, docx x1,7, pptx x2,1. Plain text files do not change.
- Batch size (MEASURED, 1.800-cell xlsx, 20,3 s today): 8 -> 9,44 s, 32 -> 6,13 s, 128 -> 5,09 s. Use 128. Memory stays bounded because Presidio's `process_batch` is a generator.
- Risk to detection: none. Output byte-identical. Presidio's `analyze()` accepts precomputed `nlp_artifacts`.
- Change:

```python
# detectors/engine.py
def detect_many(fragments, config, progress=None):
    if config.gliner is not None and config.gliner.enabled:
        return [detect(f, config) for f in fragments]
    analyzer = _base_analyzer(config.language)
    jobs = []                                  # (fragment_idx, base, window)
    for i, frag in enumerate(fragments):
        if len(frag) <= MAX_ANALYZE_CHARS:
            jobs.append((i, 0, frag))
        else:
            jobs += [(i, b, w) for b, w in iter_chunks(frag, MAX_ANALYZE_CHARS, _CHUNK_OVERLAP)]
    ad_hoc = [_deny_cached(tuple(config.deny_list))] if config.deny_list else []
    arts = analyzer.nlp_engine.process_batch([w for _, _, w in jobs], config.language, batch_size=128)
    per = [[] for _ in fragments]
    for n, ((i, base, _), (text, art)) in enumerate(zip(jobs, arts), 1):
        raw = analyzer.analyze(text=text, language=config.language,
                               ad_hoc_recognizers=ad_hoc, nlp_artifacts=art)
        ents = [Entity(r.start, r.end, normalize_type(r.entity_type), r.score, text[r.start:r.end]) for r in raw]
        per[i].append((base, _resolve_overlaps([e for e in ents if e.score >= config.low_threshold])))
        if progress and n % 64 == 0: progress(n, len(jobs))
    # then merge each fragment exactly as detect() does now:
    # a seen-set plus _resolve_overlaps for chunked fragments
```

### 2. Spread windows over worker processes

- Where: `core/plan.py:155-215`; the scan uses one core.
- File-level pool (MEASURED, with finding 1): 1 worker 62,4 s, 2 -> 45,1 s, 4 -> 42,8 s, 6 -> 44,9 s. It stops scaling because the largest file is the critical path.
- Window-level pool (MEASURED, with finding 1, including worker spawn and model load): 4 workers **24,6 s**, 6 workers **21,3 s**. x5,6 and x6,4 against today. Output identical.
- Memory (MEASURED): about 830 MB peak per worker (411,5 MB are the static vectors). 4 workers plus parent: 3.372 MB.
- Fixed cost (ESTIMATED): 3 to 10 s per worker to import and load, in parallel. Use the pool only above about 200 KB of text or 1.000 fragments.
- Change: `ProcessPoolExecutor` with an initializer that builds the analyzer; batches of about 20.000 to 50.000 characters; merge per fragment as `detect()` does; workers = min(4, cores / 2, free RAM in GB - 1); `multiprocessing.freeze_support()` first in `__main__.main` (PyInstaller needs it); `shutdown(cancel_futures=True)` for cancel.

### 3. Build one-dir instead of one-file

- Where: `packaging/thickanon.spec:61-83`.
- Now: every launch unpacks 738,0 MB into `%TEMP%\_MEI*` (MEASURED from the TOC), and Windows Defender scans the new files.
- Gain (MEASURED under load, ranges): `--help` one-dir 3,7 to 10,3 s against one-file 22,3 to 33,9 s. Best against best, the unpack costs about **12 to 19 s per launch**.
- Risk to detection: none.
- Change: `EXE(pyz, a.scripts, [], exclude_binaries=True, ...)` and `COLLECT(exe, a.binaries, a.datas, name="thickAnonymizer")`. Ship the folder as a zip or with a small installer. The splash still works. Do not use UPX (slower DLL load, antivirus false positives).

### 4. `apply_tokens` is quadratic

- Where: `core/anonymize.py:10-16`. `text = text[:e.start] + token + text[e.end:]` copies the whole text for every entity.
- MEASURED (pinned, one entity per 100 characters):

| Size | Entities | Now | Join |
|---:|---:|---:|---:|
| 100 KB | 1.024 | 13,3 ms | 2,7 ms |
| 500 KB | 5.120 | 2.349,6 ms | 10,5 ms |
| 1 MB | 10.485 | **13.772,3 ms** | **22,4 ms** |

- Output and token numbering identical. Change:

```python
ordered = sorted(entities, key=lambda x: x.start)
tokens = [mapping.token_for(e.text, e.entity_type) for e in reversed(ordered)][::-1]
parts, pos = [], 0
for e, tok in zip(ordered, tokens):
    parts.append(text[pos:e.start]); parts.append(tok); pos = e.end
parts.append(text[pos:]); return "".join(parts)
```

### 5. Trim the bundle

- Where: `thickanon.spec:16-35` and `:47-50`.
- Now (MEASURED, raw size), 738,0 MB: en_core_web_lg 445,1 MB (vectors 411,5 MB), spacy 80,9 MB (mostly `.cpp`/`.pyx`/`.pxd` sources that `collect_all` adds as data), onnxruntime 41,1 MB, PYZ 34,1 MB, blis 22,6 MB, numpy.libs 21,0 MB, PIL 13,4 MB (`_avif` 7,9 MB), hf_xet 9,5 MB, gliner 1,1 MB.
- Unused in the default exe: gliner, onnxruntime, hf_xet. Torch is excluded, so `gliner_availability()` (`ui/api.py:52-66`) always reports GLiNER as unavailable.
- Gain (MEASURED): trimmed one-dir build 561 MiB, **150 MB less (-20 %)**. ESTIMATED one-file unpack 2 to 3 s faster.
- Change: stop collecting gliner and onnxruntime; add `"gliner", "onnxruntime", "hf_xet"` to `_EXCLUDES`; drop source files with `a.datas = [d for d in a.datas if not d[0].lower().endswith((".cpp",".pyx",".pxd",".c",".h",".pyi"))]`; drop `_avif` from `a.binaries`; keep a separate spec for a GLiNER build.
- Option: `en_core_web_md` would remove about 400 MB (ESTIMATED), but its NER results differ.

### 6. Lazy imports and a background warm-up

- Where: `ui/app.py:11` imports `ui.api`, which imports `core.plan` -> `engine` -> presidio and spaCy, plus the Office libraries.
- Now (MEASURED, torch blocked): `import ui.api` takes 2,4 to 5,5 s and the window cannot open before it finishes. The first Scan then pays the analyzer build (1,4 to 1,8 s warm, 4,8 to 9,9 s cold) and the first `analyze()` (0,8 to 1,0 s).
- Gain: window opens about 2 to 2,7 s earlier; the first scan 2 to 11 s faster if the warm-up has finished.
- Change: import Presidio inside `_base_analyzer` behind a `threading.Lock` (`lru_cache` alone can build twice under concurrency); import Office handlers inside `get_handler`; after `create_window`, start a daemon thread that runs one small `detect()`. The warm-up costs about 830 MB, so skip it when the saved setting is GLiNER.

### 7. GLiNER: with the current chunk size, most of the text is never read

Correctness problem with a performance price (see quality review A1).
- MEASURED on 40 KB: with 4.000-character windows all 11 windows were cut to 384 words: 15,1 s, 306 entities. With 1.500 characters nothing is cut: 37,7 s, 668 entities (371 new, 9 lost). 2.000 characters: 34,7 s, 647 entities, some windows still cut.
- Batching via `model.inference(list, batch_size=4/8/16)`: x0,98 to x1,10. Not useful on CPU.
- Threads: 4 -> 51,7 s, 8 -> 37,4 s, default 12 -> 37,7 s. Keep the default; with finding 2 set threads to cores / workers.
- Model load: 25,6 s.

### 8. Turning off spaCy components: small gain, changes entities (not recommended)

- Parser off: x1,03 combined with finding 1, but it changes 10 entities and adds 9 (sentence boundaries stop NER spans).
- NER only (no tagger, attribute_ruler, lemmatizer): x1,26, but 178 scores change. Without lemmas the context enhancer stops raising scores (PHONE 0,75 -> 0,40).

### 9. Dev venv: importing the app also imports torch

- MEASURED: `import thickanon.ui.api` takes 48,5 to 84,0 s in the dev venv; 32,3 s of 49,0 s come from presidio `gliner_recognizer` -> gliner -> transformers -> torch, even with GLiNER off. A GLiNER exe build would pay this on every launch.
- Fix: finding 6, plus `sys.modules.setdefault("gliner", None)` before Presidio is imported when GLiNER is not requested; remove the entry again in `gliner_model._build_model` before `from gliner import GLiNER`.

### 10. Measured and not worth changing

- `MAX_ANALYZE_CHARS = 4000` is already the best value (1.000 -> x0,82, 2.000 -> x1,00, 8.000 -> x0,95, 16.000 -> x0,82, and each other size changes 8 to 55 entities).
- Packing many fragments into one window: x1,89, but 135 entities lost and 19 added. Finding 1 gives the same speed with no change.
- Rebuilding recognizers on each call: under 0,5 %.
- Skipping PhoneRecognizer on fragments without digits: only 5 % less phone time.
- PhoneRecognizer is the largest remaining cost after finding 1 (about 30 % on the xlsx). A shorter region list (DE, GB, US) would remove an ESTIMATED 50 to 60 % of it. Quality decision.
- UI: review list capped at 2.000 rows, progress queue bounded. No problem found.

## Combined

| Corpus (666 KB of text) | Time | Speed-up | Entities |
|---|---:|---:|---|
| Today, one core | 136,9 s | x1,0 | 22.890 |
| Finding 1 | 62,6 s | x2,19 | identical |
| Finding 1 + 4 workers (window level) | 24,6 s | x5,6 | identical |
| Finding 1 + 6 workers | 21,3 s | x6,4 | identical |

Start-up: one-dir saves about 12 to 19 s per launch. Trimming removes 150 MB. Lazy import plus warm-up opens the window about 2 s earlier and takes 2 to 11 s off the first scan.

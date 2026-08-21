# thickAnonymizer - desktop UI modernization

**Date:** 2026-08-21
**Status:** Approved design, pending spec review
**Supersedes:** the UI portions of `2026-05-29-thickanonymizer-design.md` (section 6, and the `ui/` shell in section 3). The core detection, mapping, IO and CLI design in that document stands unchanged.

## 1. Purpose

The core engine (detectors, mapping, IO, orchestrator) is complete and covered by 82 passing
tests. The desktop shell on top of it is not. It has broken drag-and-drop, its default review
mode silently does nothing, it discards the audit report it already receives, and it offers a
neural-NER toggle that cannot work in the distributed exe.

This design makes the desktop app the primary, shippable interface: correct, reviewable,
recoverable, and packaged as one self-contained Windows exe that can be handed to a colleague.

## 2. Defects this design fixes

Each item below is a defect in the current `src/thickanon/ui/` layer, verified by reading the code.

| # | Defect | Location |
|---|--------|----------|
| D1 | Drag-and-drop yields bare filenames, not paths. `File.path` does not exist in WebView2/Chromium, so the handler falls back to `f.name`, which then resolves against the process working directory. | `ui/web/index.html:78` |
| D2 | `quick_review`, the default mode, silently drops every uncertain detection in the GUI: `Api.anonymize` never passes `review_callback`, and the orchestrator's documented fallback is to not apply gray-band entities. | `ui/api.py:120`, `core/orchestrator.py:57` |
| D3 | The GLiNER toggle cannot work in the shipped exe. The build excludes `torch` and `transformers`, so `from gliner import GLiNER` raises, and the user is told to `pip install gliner` inside an application that has no Python. | `packaging/thickanon.spec`, `detectors/gliner_model.py:19` |
| D4 | The backup folder accepts a relative path, resolved against the working directory rather than the root. It can land inside the root and be anonymized on a later run. The `.backup` placeholder implies a default that does not exist; blank means no backup at all. | `ui/web/index.html:39`, `core/backup.py` |
| D5 | A GLiNER threshold of `0` becomes `0.5`, because `parseFloat(v) || 0.5` treats `0` as falsy. | `ui/web/index.html:107` |
| D6 | The mapping save dialog always suggests the literal `mapping.json`, ignoring the derived `<root>.thickanon-mapping.json` the app just computed. | `ui/web/index.html:93` |
| D7 | No progress, no per-file status, no cancel. A folder scan runs for minutes behind a static "Working..." string. | `ui/web/index.html:98` |
| D8 | The full audit report is returned by the API and then thrown away. Per-file counts, skipped files with reasons, flagged counts and residual-leak counts are never shown. | `ui/api.py:128`, `ui/web/index.html:111` |
| D9 | De-anonymize reports nothing. It prints the fixed string "Deanonymized." whether it restored 400 tokens or silently skipped every file as unsupported. | `core/orchestrator.py:84`, `ui/web/index.html:117` |
| D10 | No passphrase confirmation. One typo makes the mapping, and therefore the reversal, permanently unrecoverable. | `ui/web/index.html:41` |
| D11 | No settings persistence. Every launch resets mode, deny-list, backup and mapping location. | - |
| D12 | If the WebView2 Runtime is absent, pywebview falls back to MSHTML and renders the page broken, with no explanation. | `ui/app.py` |

## 3. Decisions taken

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Review mode | Build the review panel | It is the only reason to prefer the app over the CLI, and both the original design and the README already promise it. |
| Exe flavour | Slim, roughly 600 MB, regex + spaCy | Shareable. GLiNER is detected at runtime and disabled honestly instead of erroring. |
| Destructive default | Backup on by default | Originals stay recoverable after a bad run. |
| Layout | Modernized single page | Same one-screen flow, rebuilt. Review appears as an overlay only when there is something to review. |

## 4. Architecture

The shell stays thin. All new logic that is not presentation lives in `core/`, so it is unit
testable without a window.

```
        ui/web/          (index.html + app.css + app.js)
             |  pywebview js_api (opts dicts) + evaluate_js (progress push)
        ui/api.py        session state: scan cache, cancel flag, settings
             |
        core/plan.py     scan_paths()  ->  ScanResult
                         apply_scan()  ->  BatchReport
             |
        core/orchestrator.py   anonymize_paths() = wrapper over the two
```

### 4.1 Two-phase anonymize

The current flow reads a file, detects, replaces and writes it, one file at a time, with no
opportunity to inspect anything before the write. The new flow splits that in two.

**Phase 1 - scan.** Read fragments, run detection, partition into bands. Write nothing.
Produce a `ScanResult` holding, per file, the extracted fragments and the candidate spans.

**Phase 2 - apply.** Given the scan and the set of approved candidate ids, back up, replace,
residual-scan and write.

Between the two phases the UI shows what will happen. In `quick_review` that screen contains
the review list. In the automatic modes the review list is empty and the screen is a
one-click confirmation. That confirmation is deliberate: it is the preview before a
destructive in-place write.

### 4.2 New module: `core/plan.py`

```python
@dataclass(frozen=True)
class Candidate:
    id: str              # "f0:g3:45:58:PERSON" - stable within one scan
    entity: Entity
    file_index: int
    fragment_index: int
    context: str         # up to ~120 chars of surrounding text
    context_start: int   # offset of the span within `context`
    context_end: int
    band: str            # "auto" | "review"

@dataclass
class FileScan:
    path: Path
    file_index: int
    fragments: list[str]
    candidates: list[Candidate]

@dataclass
class ScanResult:
    root: Path
    files: list[FileScan]
    skipped: dict[str, str]      # path -> reason
    text_bytes: int              # total extracted text, for the memory warning
    def review_candidates(self) -> list[Candidate]
    def auto_candidates(self) -> list[Candidate]
    def counts(self) -> dict     # by entity type, by band
```

Functions:

```python
def scan_paths(paths, root, config, progress=None, cancel=None) -> ScanResult
def apply_scan(scan, mapping, config, approved_ids=None, backup_root=None,
               progress=None, cancel=None) -> BatchReport
```

- `progress(done, total, path, stage)` is called once per file. `stage` is `"scan"` or `"apply"`.
- `cancel()` returns True to stop. It is checked between files. `scan_paths` returns the
  partial result; `apply_scan` stops before the next file, so files already written stay
  written and the report records exactly what was touched.
- `approved_ids=None` means "apply every auto-band candidate and nothing from the review
  band", which is what a headless caller wants.

Band assignment reuses `core/decide.partition` unchanged, so the three review modes keep their
existing meaning: `AUTO_REDACT` puts gray-band spans in the `auto` band, `AUTO_SKIP` drops
them, `QUICK_REVIEW` puts them in the `review` band.

### 4.3 `anonymize_paths` becomes a wrapper

```python
def anonymize_paths(paths, root, mapping, config, backup_root=None, review_callback=None):
    scan = scan_paths(paths, root, config)
    approved = _resolve_review_callback(scan, review_callback)
    return apply_scan(scan, mapping, config, approved, backup_root)
```

The public signature, the `review_callback(flagged, fragment_text, path) -> list[Entity]`
contract and the return type are unchanged, so the CLI and all existing orchestrator tests
keep passing. Those tests are the evidence that the refactor is behaviour-preserving.

`_resolve_review_callback` walks the scan file by file and fragment by fragment, calls the
callback with that fragment's review-band entities, and converts the returned entities back to
candidate ids by value equality. `Entity` is a frozen dataclass, so equality is by value and
the lookup is exact. A `None` callback yields an empty approved set, which is the documented
headless default.

One behavioural change is accepted and is an improvement: all files are now read before any
file is written, so a failure during scanning leaves every file untouched rather than half the
batch rewritten. Per-file errors still record a skip and continue.

### 4.4 De-anonymize report

`deanonymize_paths` returns a `DeanonReport`:

```python
@dataclass
class DeanonReport:
    files: dict[str, int]            # path -> tokens restored
    unknown_tokens: dict[str, int]   # token -> occurrences with no mapping entry
    skipped: dict[str, str]
    def total_restored(self) -> int
    def summary(self) -> str
    def to_dict(self) -> dict
```

Unknown tokens matter: a token in the AI's output with no mapping entry means the user has
loaded the wrong mapping file, and today that failure is completely silent. The CLI prints the
summary; the GUI shows the table.

Producing those counts needs a counting variant of the replacement itself. `core/anonymize.py`
gains `deanonymize_counted(text, mapping) -> tuple[str, int, Counter]`, returning the new text,
the number of tokens restored, and the unknown tokens encountered. The existing
`deanonymize(text, mapping) -> str` stays as a thin wrapper over it so its tests are untouched.

## 5. UI API (`ui/api.py`)

Every action takes a single `opts` dict instead of a positional argument list. The current
eleven-positional-argument call is fragile and already inconsistent between its two callers.

| Method | Returns |
|--------|---------|
| `environment()` | `{version, gliner: {available, reason}, renderer, platform}` |
| `pick_files()` / `pick_folder()` | `{ok, paths}` |
| `pick_mapping(suggested_name)` | `{ok, path}` |
| `pick_backup()` | `{ok, path}` |
| `suggest_defaults(files, root)` | `{ok, root, mapping, backup}` |
| `scan(opts)` | `{ok, scan_id, counts, review, skipped, files, warnings}` |
| `apply(scan_id, approved_ids, opts)` | `{ok, report, summary, mapping_path}` |
| `deanonymize(opts)` | `{ok, report, summary}` |
| `cancel()` | `{ok}` |
| `download_model()` | `{ok, error}` |
| `load_settings()` / `save_settings(opts)` | `{ok, settings}` |

Notes:

- **GLiNER availability** is probed with `importlib.util.find_spec` for `gliner` and `torch`.
  That is cheap and does not import torch. When unavailable, `reason` explains it in the
  language of the distributed exe ("this build ships the regex + spaCy detector only"), never
  "pip install".
- **Progress** is pushed from the worker thread with
  `window.evaluate_js("window.thickanon.onProgress({...})")`. pywebview already runs each
  js_api call on its own thread, so no extra threading is needed inside the API.
- **Scan cache.** `scan(opts)` stores the `ScanResult` on the `Api` instance under a
  `scan_id`. Only the most recent scan is kept; a new scan discards the previous one. `apply`
  with an unknown or stale `scan_id` returns a clear error telling the user to scan again.
- **Cancel** sets a `threading.Event` that the `cancel` callable reads.
- **`apply` takes `opts` again** because the mapping path, passphrase and backup folder may
  legitimately change between scanning and applying. Only the file selection and detection
  settings are frozen by the scan; changing those requires a new scan, which the UI enforces
  by invalidating the `scan_id` whenever a detection-affecting control changes.
- **Rejected candidates are simply not applied.** They are counted in the report's existing
  `flagged_count` per file, exactly as gray-band entities are today, so the report already has
  a home for them.
- **Settings** persist to `%APPDATA%\thickAnonymizer\settings.json`: mode, deny-list, backup
  enabled, last root, last mapping directory, GLiNER options, theme. The passphrase is
  **never** written.
- All methods keep the existing `{ok: False, error: str}` contract on failure. No exception
  crosses the bridge.

## 6. UI (`ui/web/`)

Split into `index.html`, `app.css`, `app.js`. All three are bundled by the PyInstaller spec.

### 6.1 Flow

```
 files -> settings -> [Scan and preview] -> progress -> review overlay (if any) -> [Apply] -> report
                   -> [De-anonymize]     -> progress -> report
```

### 6.2 Sections

1. **Drop zone and file list.** Native drop through pywebview's `window.dom` drop event, which
   supplies `pywebviewFullPath` for real paths on WebView2. Files render as removable chips
   with a "Clear all" control. Browse files and Browse folder remain, and are the guaranteed
   path on any backend that cannot supply paths.
2. **Settings card.** Mode, root, mapping with Choose, backup (checked by default, absolute
   path, Choose), passphrase with a confirmation field that appears once the first field is
   non-empty, deny-list.

   The default backup folder mirrors the mapping rule: `<root.name>.thickanon-backup` beside
   the root, in the root's parent, falling back to the home directory when the root is a drive
   root. `core/backup.py` gains the same outside-root guard the mapping already has
   (`ensure_backup_outside_root`), raising rather than copying originals into the tree that is
   about to be anonymized. Any relative path the user supplies is resolved against the root's
   parent, never the process working directory.
3. **Advanced** (`<details>`, collapsed). GLiNER toggle, labels, threshold, GPU, Download
   model. When `environment().gliner.available` is false the whole group is disabled and
   carries the reason inline.
4. **Progress.** Determinate bar, current file name, counts, elapsed time, Cancel.
5. **Review overlay.** Shown only when the scan produced review-band candidates. Grouped by
   entity type. Each row: the context snippet with the span highlighted, the entity type, the
   score, the file. A checkbox per row, approve-all and reject-all per group, and globally.
   The footer states exactly what the button will do: "Apply 143 replacements to 12 files".
6. **Report panel.** Headline numbers, totals by entity type, a per-file table (applied,
   left, residual), a skipped table with reasons, a red banner when residual leaks are
   non-zero, and Copy report / Save report JSON.

### 6.3 Styling

CSS custom properties for the whole palette; light and dark via `prefers-color-scheme` with a
manual override stored in settings. System font stack. Visible focus rings on every control.
No inline event handlers: `addEventListener` throughout. Responsive down to roughly 700px.
Destructive actions (Apply, De-anonymize) are visually distinct from navigation.

## 7. Packaging

- `packaging/make_icon.py` generates `packaging/icon.ico` with Pillow. The `.ico` is committed
  as a generated artifact so a build does not require Pillow.
- `packaging/version_info.txt` gives the exe product name, version and copyright in Windows
  file properties.
- **Splash screen.** PyInstaller's Tk splash, shown during onefile extraction and closed by
  the app once the window exists. A 580 MB onefile takes roughly 15 seconds to unpack, during
  which a double-click currently looks like nothing happened. Costs about 10 MB of tkinter in
  the bundle.
- `packaging/build.ps1`: clean, build, then print the exe path, size and SHA256.
- The spec keeps `console=True` and the `__main__.py` argv dispatch, so the one exe remains
  both GUI and CLI. `torch` and `transformers` stay excluded.

## 8. WebView2 preflight

`ui/app.py` checks for the WebView2 Runtime before creating the window. If it is missing, show
a native message box naming the runtime and its download URL, and exit, instead of falling
back to MSHTML and rendering an unusable page. Detection reads the registry key that the
Evergreen runtime installs, and falls back to letting pywebview choose if the check itself
fails, so a false negative can never block a working machine.

## 9. Error handling

- Per-file failures during scan or apply record a skip with a reason, and the batch continues.
- Cancel during apply leaves already-written files written; the report states exactly which.
- A stale or unknown `scan_id` produces a clear "the file selection changed, scan again".
- Mapping decrypt failure keeps its existing clear error and writes nothing.
- Extracted text above 200 MB produces a warning in the scan result, surfaced in the UI. It is
  not a hard failure.

## 10. Testing

New:

- `tests/core/test_plan.py` - candidate ids are stable and unique; bands follow the mode;
  `apply_scan` writes only approved plus auto candidates; `progress` is called once per file;
  `cancel` stops between files and the report reflects the partial run; scanning writes nothing.
- `tests/core/test_deanon_report.py` - restored counts per file, unknown tokens detected,
  unsupported files recorded.
- `tests/ui/test_api.py` extended - scan then apply session flow, approved-id filtering, stale
  `scan_id` error, `environment()` shape, settings round-trip excluding the passphrase, the
  `opts`-dict signature, backup path forced absolute and outside root.

Unchanged and used as the regression gate: all 82 currently-passing tests, in particular
`tests/core/test_orchestrator.py` and `tests/test_cli.py`, which must pass untouched to prove
`anonymize_paths` kept its behaviour.

Manual, and recorded in the plan as explicit steps because they cannot be automated here:
build the exe, launch it by double-click, drag a folder onto it, run a full scan / review /
apply / de-anonymize cycle, and confirm the CLI path still works from a terminal.

## 11. Trade-offs accepted

- **Memory.** The scan holds all extracted text. Acceptable for document folders, where the
  text is a small fraction of the bytes on disk. Mitigated by the 200 MB warning.
- **One extra click** in the automatic modes. Deliberate: it is the preview before a
  destructive write.
- **Splash size.** Roughly 10 MB of tkinter, in exchange for a double-click that visibly
  responds.
- **Drop paths are a WebView2 feature.** Other backends degrade to the Browse buttons, which
  always work.

## 12. Out of scope

- PDF and OCR support.
- Changing the CLI's argument surface, beyond printing the new de-anonymize report.
- Any change to detection quality, thresholds or recognizers.
- A GLiNER-bundled build. The documented path for producing one is kept, but it is not built
  or tested here.

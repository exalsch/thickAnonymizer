# thickAnonymizer

Mass-anonymize files into readable tokens (`[PERSON_1]`, `[IP_1]`, `[HOST_1]`)
before using them with AI tools, then de-anonymize the AI's output back.

> ⚠️ **Status: under active development (v0.1.0, alpha).** This project is a
> work in progress and is **not yet production-ready**. APIs, the CLI, and
> output formats may change without notice, and detection is not guaranteed to
> catch every piece of PII - see [Known limitations](#known-limitations) below.
> Review the residual-leak report before sharing any anonymized output, and use
> at your own risk.

## Install (dev)
    pip install -e ".[dev]"
    python -m spacy download en_core_web_lg

For the exact versions the tests and the exe build were verified with, sync the
venv from the hashed lock file instead (needs [uv](https://docs.astral.sh/uv/)):

    uv pip sync -p venv\Scripts\python.exe requirements-lock.txt
    uv pip install -p venv\Scripts\python.exe -e . --no-deps

The lock file includes the spaCy model and the `[dev]` extra.

### Updating dependencies

1. Regenerate the lock with the command at the top of `requirements-lock.txt`
   (add `--upgrade` to move every package to its latest compatible version).
2. Sync the venv as above, then run `python -m pytest -q`. The real-model GLiNER
   test runs automatically when the default model is in the Hugging Face cache.
3. Run `python -m pip_audit -l` and expect "No known vulnerabilities found".
4. Raise the lower bounds in `pyproject.toml` to the versions you verified.

`en_core_web_lg` is pinned to 3.8.0 and needs spaCy 3.8.x, so `pyproject.toml`
caps spaCy below 3.9. Moving to a new spaCy minor version needs the matching model
version in `packaging/spacy-model.in`.

## CLI
    thickanon anonymize C:\data --root C:\data --mapping C:\keys\map.json --mode quick_review
    thickanon deanonymize C:\data --mapping C:\keys\map.json

`anon` / `deanon` are accepted as short aliases for `anonymize` / `deanonymize`.

> **Rule:** the `--mapping` file MUST live OUTSIDE the `--root` folder. The mapping
> is the reversible key; if it sat inside the folder you anonymize and share, it
> would leak alongside the files and let anyone fully de-anonymize them. The tool
> refuses to run if the mapping path is inside root.

## Desktop app

    python -m thickanon.ui.app

Or double-click `thickAnonymizer.exe`.

The app works in three steps.

1. **Choose files.** Drag files or a folder onto the window, or use
   **Browse files... / Browse folder...**. **Root folder**, **Mapping file** and
   **Backup folder** fill in automatically, always placed *beside* the root and
   never inside it.
2. **Scan and preview.** Nothing is written yet. The app reads and analyses every
   file and tells you what it found. In **Quick review** mode, detections it is not
   confident about are listed with the value highlighted in its surrounding text, so
   you approve or reject them in one pass.
3. **Apply.** The approved replacements are written, originals are copied to the
   backup folder first, and the mapping is saved. A backup is never overwritten: if
   you run the tool twice over the same folder, the backup keeps the first original
   it saw, which is the one you would actually want back. The report shows per-file counts,
   skipped files with reasons, and a loud warning if any email or IP pattern survived
   into the written files.

**De-anonymize** takes the AI's output plus the mapping file and restores the real
values. It reports how many tokens it restored, and warns when a file contains tokens
this mapping does not know about, which almost always means the wrong mapping file.

Backups are **on by default**. Files are edited in place, so with backups off the
originals are gone.

### Requirements for the exe

The desktop window needs the **Microsoft Edge WebView2 Runtime**, which ships with
Windows 11 and current Windows 10. If it is missing, the app says so and links to the
download instead of opening a broken window. The command-line mode does not need it.

## Build a Windows .exe (single hybrid binary)

    .\packaging\build.ps1
    # dist/thickAnonymizer.exe  (488 MB)

The script cleans the previous build, runs PyInstaller, smoke-tests the exe and refuses
to report success if it cannot run, and prints the size and SHA256 of the result so a
shared copy can be verified. `pyinstaller packaging/thickanon.spec` still works if you
prefer to drive it yourself.

One exe does **both** roles, dispatching on its arguments (`thickanon/__main__.py`):

- **Double-click** (no arguments) -> a splash appears while the one-file archive
  unpacks, then the desktop **GUI**. The splash reports progress while the app
  unpacks and starts, so a slow first launch does not look like a hang. The exe
  is a console binary, so a console window flashes briefly and is then hidden;
  only the app window remains.
- **From a terminal** with arguments -> the **CLI**, e.g.
  `thickAnonymizer.exe anon C:\data --root C:\data --mapping C:\keys\map.json --mode auto_redact`.
  Because it is a console-subsystem exe, the shell waits for it, stdout/stderr pipe and
  redirect normally, and the exit code propagates.

The spaCy model, the web UI and the splash are bundled inside the exe; no Python install
is needed on the target machine.

The exe does not contain PyTorch. spaCy's `en_core_web_lg` runs on thinc/numpy, and
GLiNER runs as an ONNX model on onnxruntime, so the default exe offers both detectors.
The GLiNER model itself is not bundled; it is downloaded on first use (see below).

## Neural NER detection (GLiNER)

GLiNER is a neural model that finds names, organizations, addresses, usernames and
hostnames that the regex + spaCy detector misses, in English and German among other
languages. In the 23.11.2026 benchmark on IT text (tickets, logs, mails) it found
93,9 % of the personal data, against 62,2 % for regex + spaCy, but it is about 28 times
slower (`docs/reviews/2026-11-23-model-research.md`).

It needs no extra install: onnxruntime and tokenizers are regular dependencies.

Enable it:

- **CLI:** pass `--gliner` (optionally configure `--gliner-labels "person,organization,email"`
  and `--gliner-threshold 0.5`).
- **Desktop app:** toggle **Use neural NER (GLiNER)** in the settings panel.

The model is `onnx-community/gliner_multi_pii-v1` (the ONNX export of
`urchade/gliner_multi_pii-v1`, Apache-2.0, 1,16 GB), pinned to one revision. On first
use it is downloaded into the Hugging Face cache (`~/.cache/huggingface/`); after that
it is loaded from the cache without touching the network. To pre-fetch it before going
offline:

    thickanon download-model

`--gliner-model <dir>` loads a model from a local folder instead. The folder must hold
an ONNX export: `gliner_config.json`, `tokenizer.json` and `onnx/model.onnx`. A folder
with only a PyTorch checkpoint (`pytorch_model.bin`) is refused with a clear message.

**Important notes:**

- The model is loaded **once per process**. Pass a folder to `anonymize` instead
  of looping the exe per file - restarting per file re-pays the model load cost.
- The text is read in windows of 96 words, because the model reads at most 384 words
  per call and silently drops the rest.
- **GPU acceleration** (`--gliner-gpu`) needs a GPU build of onnxruntime
  (`onnxruntime-gpu` for NVIDIA CUDA or `onnxruntime-directml`). With only the CPU
  runtime installed, GPU mode stops with a clear message.
- GLiNER's real per-entity confidence scores feed the normal review bands
  (below `low_threshold` → ignored; above `high_threshold` → auto-anonymized;
  in between → gray band / human review).
- If GLiNER mode is enabled but the model cannot be loaded, every file fails to
  scan and is recorded as skipped, with the loader's error as the reason. Nothing
  is silently anonymized with a weaker detector, but do read the skipped list:
  a run where every file was skipped anonymized nothing at all.
- GLiNER sometimes marks product names as hostnames (for example "M3"). Review the
  gray band before applying.

## What is read in Office files

docx, xlsx and pptx files are read part by part, not only their main body:

- **Word:** body, headers, footers, footnotes, endnotes, comments, text boxes, content
  controls, nested tables, tracked insertions and deletions, and field codes.
- **Excel:** cell text, sheet names, cell comments, headers and footers, string literals
  in formulas, defined names and data validation lists, and hyperlink text.
- **PowerPoint:** slides, group shapes, tables, speaker notes, comments, charts and the
  footer and date text of masters. The prompt text of master placeholders ("Click to
  edit Master title style") is skipped.
- **All three:** chart data, external link targets (`mailto:`, URLs, file paths), the
  alt text of pictures, and Office files embedded in the file, such as a chart's
  workbook.

Fields that identify a person by definition are **cleared on every write** instead of
being detected: the document properties (author, last modified by, title, subject,
keywords, comments, company, manager), custom properties, and the author names,
initials and user IDs of comments and tracked changes. These cannot be restored by
de-anonymize.

Excel forbids `[` and `]` in sheet names, so a token in a sheet name is written as
`⟦PERSON_1⟧`. Formulas, defined names and charts that refer to the sheet are updated,
and de-anonymize restores the original name. A file is refused when the anonymized
sheet name would be longer than the 31 characters Excel allows.

## Known limitations

- **Residual leaks are REPORTED, not blocked:** in `auto_skip` mode and in non-interactive
  `quick_review`, the output file may still contain low-confidence PII. Check the report's
  residual-leak warning before sharing anything.
- **CLI `quick_review` (the default) drops uncertain detections** because there is no
  interactive reviewer on the CLI; use `--mode auto_redact` or the desktop app, which
  lists them for approval.
- **The desktop app holds the extracted text of the whole selection in memory** while
  you preview it. It warns above roughly 200 MB of text; anonymize very large trees in
  batches.
- **xlsx formulas:** only the string literals inside a formula are anonymized
  (`=HYPERLINK("mailto:...","Name")`). Numbers are never anonymized, so a phone number
  stored as a number stays.
- **Run formatting:** text outside a replaced value keeps its formatting. A token that
  replaces a value spread over differently formatted runs takes the formatting of the
  run where the value started.
- **Pictures and non-Office embedded objects are not read.** Text inside an image, image
  metadata (EXIF) and embedded PDFs or OLE binaries stay as they are.
- **The residual safety-net scan only catches IPv4 and email** (narrower than primary detection).
- **The mapping file defaults to plaintext and IS the sensitive data** - always use a passphrase (`--passphrase` / the UI field) when the mapping could be exposed.
- **Deny-list matching is exact (case-insensitive), not fuzzy.**
- **PDFs and scanned documents are out of scope in v1.**

## License

[MIT](LICENSE) © 2026 Alex Schick.

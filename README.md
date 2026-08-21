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

The script cleans the previous build, runs PyInstaller, and prints the size and SHA256
of the result so a shared copy can be verified. `pyinstaller packaging/thickanon.spec`
still works if you prefer to drive it yourself.

One exe does **both** roles, dispatching on its arguments (`thickanon/__main__.py`):

- **Double-click** (no arguments) -> a splash appears while the one-file archive
  unpacks, then the desktop **GUI**. The exe is a console binary, so a console window
  flashes briefly and is then hidden; only the app window remains.
- **From a terminal** with arguments -> the **CLI**, e.g.
  `thickAnonymizer.exe anon C:\data --root C:\data --mapping C:\keys\map.json --mode auto_redact`.
  Because it is a console-subsystem exe, the shell waits for it, stdout/stderr pipe and
  redirect normally, and the exit code propagates.

The spaCy model, the web UI and the splash are bundled inside the exe; no Python install
is needed on the target machine.

The build excludes the PyTorch/CUDA stack: the `en_core_web_lg` pipeline is a CNN model
that runs on thinc/numpy, so torch is unused for inference and dropping it takes the exe
from ~3.1 GB to under 500 MB. The default exe therefore ships the **regex + spaCy**
detector only, and the app's neural-NER controls are disabled with an explanation rather
than failing at run time. To bundle the **optional GLiNER** backend, install the
`[gliner]` extra and remove `"torch"`/`"transformers"` from `_EXCLUDES` in
`packaging/thickanon.spec` before building - the exe will grow accordingly.

## Neural NER detection (GLiNER, optional)

Install the extra:

    pip install -e ".[dev,gliner]"
    # or just the runtime:
    pip install gliner

This pulls the `gliner` package plus onnxruntime, transformers, and CPU-only PyTorch
(~200 MB), all with prebuilt wheels for Windows / Python 3.13.

Enable it:

- **CLI:** pass `--gliner` (optionally configure `--gliner-labels "person,organization,email"`
  and `--gliner-threshold 0.5`).
- **Desktop app:** toggle **Use neural NER (GLiNER)** in the settings panel.

On first run the default GLiNER model is downloaded automatically into the
Hugging Face cache (`~/.cache/huggingface/`). To pre-fetch it before going offline:

    thickanon download-model

(Pass `--gliner-model <dir>` to load a model from a specific local directory instead.)

**Important notes:**

- The model is loaded **once per process**. Pass a folder to `anonymize` instead
  of looping the exe per file - restarting per file re-pays the model load cost.
- **GPU acceleration** (`--gliner-gpu`) requires a CUDA-enabled PyTorch install;
  the default torch wheel is CPU-only.
- GLiNER's real per-entity confidence scores feed the normal review bands
  (below `low_threshold` → ignored; above `high_threshold` → auto-anonymized;
  in between → gray band / human review).
- If GLiNER mode is enabled but the model cannot be loaded, every file fails to
  scan and is recorded as skipped, with the loader's error as the reason. Nothing
  is silently anonymized with a weaker detector, but do read the skipped list:
  a run where every file was skipped anonymized nothing at all.

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
- **xlsx formula cells are skipped** - PII inside spreadsheet formulas is not anonymized.
- **.docx/.pptx run formatting:** when a paragraph is modified, inline run-level formatting collapses to the paragraph's first run (paragraph-level formatting is preserved; mid-paragraph bold/italic on edited paragraphs is not).
- **The residual safety-net scan only catches IPv4 and email** (narrower than primary detection).
- **The mapping file defaults to plaintext and IS the sensitive data** - always use a passphrase (`--passphrase` / the UI field) when the mapping could be exposed.
- **Deny-list matching is exact (case-insensitive), not fuzzy.**
- **PDFs and scanned documents are out of scope in v1.**

## License

[MIT](LICENSE) © 2026 Alex Schick.

# thickAnonymizer

Mass-anonymize files into readable tokens (`[PERSON_1]`, `[IP_1]`, `[HOST_1]`)
before using them with AI tools, then de-anonymize the AI's output back.

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

Drag files or a folder onto the window (or use **Browse files… / Browse folder…**).
**Root folder** and **Mapping file** auto-fill from your selection — the mapping defaults
to a path *beside* the root (never inside it). Use **Choose…** to pick a mapping path
yourself.

## Build a Windows .exe (single hybrid binary)
    pyinstaller packaging/thickanon.spec
    # dist/thickAnonymizer.exe

One exe does **both** roles, dispatching on its arguments (`thickanon/__main__.py`):

- **Double-click** (no arguments) → opens the desktop **GUI**. The exe is a console
  binary, so a console window flashes for a fraction of a second and is then hidden;
  only the app window remains.
- **From a terminal** with arguments → runs the **CLI**, e.g.
  `thickAnonymizer.exe anon C:\data --root C:\data --mapping C:\keys\map.json --mode auto_redact`.
  Because it is built as a console-subsystem exe, the shell waits for it, stdout/stderr
  pipe and redirect normally, and the exit code propagates — so it scripts like a normal
  CLI tool.

The spaCy model and web UI are bundled inside the exe; no Python install is needed on the
target machine. (In a dev checkout, `thickanon` is the console-script entry point and
`python -m thickanon` behaves identically to the exe.)

## Known limitations

- **Residual leaks are REPORTED, not blocked:** in `auto_skip` mode and in non-interactive `quick_review`, the output file may still contain low-confidence PII. Check the report's "RESIDUAL LEAKS FLAGGED" count before sharing.
- **CLI `quick_review` (the default) drops uncertain detections** because there is no interactive reviewer on the CLI; use `--mode auto_redact` or the desktop app.
- **xlsx formula cells are skipped** — PII inside spreadsheet formulas is not anonymized.
- **.docx/.pptx run formatting:** when a paragraph is modified, inline run-level formatting collapses to the paragraph's first run (paragraph-level formatting is preserved; mid-paragraph bold/italic on edited paragraphs is not).
- **The residual safety-net scan only catches IPv4 and email** (narrower than primary detection).
- **The mapping file defaults to plaintext and IS the sensitive data** — always use a passphrase (`--passphrase` / the UI field) when the mapping could be exposed.
- **Deny-list matching is exact (case-insensitive), not fuzzy.**
- **PDFs and scanned documents are out of scope in v1.**

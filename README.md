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

## Build a Windows .exe
    pyinstaller packaging/thickanon.spec
    # dist/thickAnonymizer.exe

The exe **is** the desktop app: its entry point is `thickanon/ui/app.py` built with
`console=False`, so **double-clicking `dist/thickAnonymizer.exe` opens the GUI window
directly** — no terminal, no Python install needed on the target machine. The spaCy
model and web UI are bundled inside the exe. (The CLI is the dev/console entry point
`thickanon`; the packaged exe ships the GUI.)

## Known limitations

- **Residual leaks are REPORTED, not blocked:** in `auto_skip` mode and in non-interactive `quick_review`, the output file may still contain low-confidence PII. Check the report's "RESIDUAL LEAKS FLAGGED" count before sharing.
- **CLI `quick_review` (the default) drops uncertain detections** because there is no interactive reviewer on the CLI; use `--mode auto_redact` or the desktop app.
- **xlsx formula cells are skipped** — PII inside spreadsheet formulas is not anonymized.
- **.docx/.pptx run formatting:** when a paragraph is modified, inline run-level formatting collapses to the paragraph's first run (paragraph-level formatting is preserved; mid-paragraph bold/italic on edited paragraphs is not).
- **The residual safety-net scan only catches IPv4 and email** (narrower than primary detection).
- **The mapping file defaults to plaintext and IS the sensitive data** — always use a passphrase (`--passphrase` / the UI field) when the mapping could be exposed.
- **Deny-list matching is exact (case-insensitive), not fuzzy.**
- **PDFs and scanned documents are out of scope in v1.**

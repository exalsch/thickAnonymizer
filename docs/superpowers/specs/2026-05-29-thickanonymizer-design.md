# thickAnonymizer — Design

**Date:** 2026-05-29
**Status:** Approved design, pending spec review

## 1. Purpose

A Windows tool to anonymize files **en masse** before using them with external AI tools,
and to **de-anonymize** AI output back to the real values afterward. PII, IP addresses,
and hostnames/FQDNs are replaced with **readable, consistent tokens** (`[PERSON_1]`,
`[IP_1]`, `[HOST_1]`). A reversible mapping links each token to its original value so the
process can be undone.

Ships as both:
- a **native desktop app** (PyWebView window with drag-and-drop), and
- a **CLI**,

both sitting on top of a single shared Python core built on **Microsoft Presidio**.

## 2. Goals & non-goals

**Goals**
- Mass-anonymize a folder/selection of files in one pass.
- Reversible: restore original values from AI output via a saved mapping.
- High recall on structured data (IP/FQDN/email/cards) and a known deny-list.
- Smooth UX: confident detections are automatic; only ambiguous spans need review.
- Preserve file formatting (Office docs edited in place, not flattened to text).

**Non-goals**
- Statistical/dataset anonymization (k-anonymity etc. — that's ARX's domain).
- Sending any data to a remote service. Everything runs locally.
- Scanned-PDF OCR (out of scope for v1; PDFs not in the initial file-type set).

## 3. Architecture

```
┌─────────────┐   ┌─────────────┐
│  PyWebView  │   │     CLI     │     ← thin shells, no business logic
│ (drag-drop) │   │ (argparse)  │
└──────┬──────┘   └──────┬──────┘
       └────────┬────────┘
        ┌───────▼─────────┐
        │   core engine    │  anonymize() / deanonymize()
        ├──────────────────┤
        │ detectors │ io (readers/writers) │ mapping store │
        └──────────────────┘
```

- **`core/`** — pure Python, no UI dependencies. Fully unit-testable in isolation.
  Exposes `anonymize(inputs, config)` and `deanonymize(inputs, mapping)`.
- **`detectors/`** — Presidio AnalyzerEngine + custom regex recognizers + deny-list matcher.
- **`io/`** — per-format readers/writers that preserve formatting.
- **`mapping/`** — the reversible token↔value store.
- **`ui/`** (PyWebView) and **`cli/`** — thin shells that only call the core.

Each unit has one purpose and a defined interface, so it can be understood and tested
independently.

## 4. File-type handling

| Type | Library | Strategy |
|------|---------|----------|
| `.txt`, `.md`, `.csv`, source code | stdlib | Read text, replace spans, write back. |
| `.docx` | python-docx | Edit text runs **in place**; formatting preserved. |
| `.xlsx` | openpyxl | Edit cell values **in place**; formulas/styles preserved. |
| `.pptx` | python-pptx | Edit text frames **in place**. |

Unsupported or corrupt files are **skipped** and recorded in the audit report — a batch
never half-fails silently.

## 5. Detection pipeline (lean-safe / over-redact)

1. **Regex recognizers** for structured data — IP (v4/v6), FQDN/hostname, email,
   credit-card (Luhn-validated), IBAN. Near-100% recall.
2. **Presidio NLP** scores names/orgs/locations. Threshold leans **safe (low)** so we
   over-redact rather than miss.
3. **Deny-list** — user-supplied known-sensitive terms (project codenames, customer names,
   internal domains like `*.acme.local`). Exact/fuzzy matches are **always** replaced,
   no model involved. Biggest lever for org-specific data.
4. **Confidence bands:**
   - `≥ high` → anonymize automatically.
   - **gray band** → handled per the selected mode (see §6).
5. **Residual leak scan** — after writing output, re-scan it for anything still matching a
   PII pattern (stray IP, email, etc.) and flag loudly. Safety net for model misses.
6. **Audit report** per batch — counts by entity type, list of replacements, and the short
   "⚠️ N flagged items" list.

## 6. Review modes (configurable; quick-review is default)

- **Quick review (default):** confident hits anonymized automatically; only gray-band spans
  are collected into one panel, approved/rejected in bulk. Confident files never need opening.
- **Fully automatic — over-redact:** gray-band spans anonymized automatically; user just
  reads the audit report.
- **Fully automatic — skip:** only high-confidence hits anonymized; gray band left, relying
  on the residual scan.

## 7. Reversible mapping

- One **consistent bidirectional map per batch**: same real value → same token everywhere;
  same token → exactly one real value.
- Token format: `[TYPE_N]` (e.g. `[PERSON_1]`, `[IP_3]`, `[HOST_2]`) — designed to survive
  a verbatim round-trip through an AI tool.
- Stored as `mapping.json` next to the output. **Optionally encrypted** with a user passphrase
  (AES via the `cryptography` library). **Default: local plaintext** for smoothness;
  encryption recommended since this file *is* the sensitive data. The mapping never leaves
  the machine.
- **De-anonymize flow:** drop the AI's output (text or file) back in → core applies the
  reverse map → real values restored.

## 8. Backup option

- **Default: in-place edit** (originals overwritten with anonymized versions).
- **Optional backup:** when enabled, originals are copied to a chosen backup folder
  (default `.backup/`) **before** any edit. Recommended for first runs.
- Backup is independent of the mapping file (one protects the source files, the other
  enables reversal).

## 9. Error handling

- Unsupported/corrupt files: skipped, logged in the report, batch continues.
- Mapping decrypt failure (wrong passphrase): clear error, no partial writes.
- Write failures: original left intact (or restored from backup if enabled).

## 10. Testing strategy (TDD on the core)

- **Golden-file tests** per format (txt/csv/docx/xlsx/pptx): known input → known output.
- **Consistency tests:** same value always maps to the same token within a batch.
- **Round-trip tests:** `deanonymize(anonymize(x)) == x`.
- **Detector tests:** IP/FQDN/email/card regex recall; deny-list always-match; threshold behavior.
- **Residual-scan tests:** seeded leaks are caught.
- **Mapping tests:** encryption round-trip, wrong-passphrase failure.

## 11. Tech stack

- Python 3.11+
- microsoft-presidio (analyzer + anonymizer), spaCy model for NLP
- python-docx, openpyxl, python-pptx
- cryptography (optional mapping encryption)
- pywebview (desktop shell), packaged to `.exe` via PyInstaller
- pytest (tests)

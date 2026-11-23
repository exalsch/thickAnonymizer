# thickanon - anonymization outcome and correctness review

Date: 23.11.2026. Reviewer: a Claude Code subagent. Baseline: `pytest -q` 275 passed, 1 skipped.
Versions at review time: presidio_analyzer 2.2.364, spaCy 3.8.15, python-docx 1.2.0, python-pptx 1.0.2, openpyxl 3.1.5, gliner 0.2.28.

VERIFIED means a probe script reproduced the problem. SUSPECTED means it was found by reading the code only.
The probe scripts were kept in the session scratchpad only (`probe_detect.py`, `probe_core.py`, `probe_chunk.py`, `probe_propagate.py`, `probe_io.py`, `probe_docx2.py`, `probe_misc.py`, `probe_gliner.py`).

## A. PII leaks

**A1. GLiNER mode reads only the first ~384 words of each 4.000-char chunk - LEAK, VERIFIED**
- Location: `core/types.py:37` (`max_chunk_chars = 4000`) and `detectors/gliner.py:27`.
- Cause: `urchade/gliner_multi_pii-v1` has `config.max_len = 384` words and truncates longer input silently.
- Probe: "Please contact Dr. Eleanor Whitfield..." is found with ~350 filler words in front of it (1.781 chars). With ~420 words (2.101 chars) or ~770 words (3.701 chars) in front, it is not found.
- Effect: chunks step by 3.800 chars, so no chunk covers the tail of the one before. About 40-50 % of any text longer than ~1.800 chars gets only the regex recognizers.
- Fix: chunk by words. Use about `model.config.max_len - 40` words per chunk with ~50 words overlap, or about 1.200 chars. Add a test that puts a name at word 500.

**A2. Office parts that are never read - LEAK, VERIFIED** (each file unzipped after an AUTO_REDACT run; the report said `residual_count: 0` for all three)
- docx (`io/docx.py:4-9` reads only body paragraphs and top-level tables). Not anonymized: header1.xml and footer1.xml, nested tables, text boxes (`w:txbxContent`), content controls (`w:sdt`), tracked changes (`w:ins`, `w:delText`, and the `w:author` attribute), `mailto:` hyperlink targets in document.xml.rels. SUSPECTED: footnotes, endnotes, comments.xml.
- xlsx (`io/xlsx.py:4-13`). Not anonymized: sheet names, formulas (skipped on purpose, so `=HYPERLINK("mailto:...","Name")` stays in full), cell comments (text and author), hyperlink targets, header and footer, phone numbers stored as numbers. SUSPECTED: defined names, data validation lists, chart titles, pivotCacheRecords.
- pptx (`io/pptx.py:4-10` reads only top-level shapes). Not anonymized: group shapes, tables (graphicFrame), speaker notes. SUSPECTED: charts, SmartArt, layouts and masters, comments.
- Fix docx: walk all `w:p` in document, header, footer, footnotes, endnotes and comments parts, including txbx, sdt and ins. Handle revisions first (accept, reject or refuse). Rewrite rels hyperlink targets.
- Fix xlsx: add sheet titles, comments, header and footer, hyperlink targets, string literals inside formulas, and an option for numeric cells.
- Fix pptx: recurse into GroupShape, read table cells and notes_slide.
- Test: one generic "build, apply, unzip, grep every part" test per format.

**A3. Metadata leaks in all three formats - LEAK, VERIFIED**
- docProps/core.xml keeps author, last_modified_by, title and comments. No handler touches core_properties.
- Fix: anonymize title, subject, keywords and comments. Blank the author fields. Clear Company and Manager in app.xml.

**A4. A detected value is not replaced where the detector misses it - LEAK, VERIFIED** (`core/plan.py:188`, `:272`)
- "Jane Doe" in 1.txt becomes [PERSON_1]. In 2.txt, "doe approved. ticket owner: jdoe. cc Doe" stays unchanged. In "ping srvm3prd01" the short host name stays, although `srvm3prd01.example.local` is in the mapping.
- Fix: a propagation pass between scan and apply. Search all fragments for all accepted values, plus PERSON name parts (3 letters or more), the first label of HOST values and the local part of EMAIL values. Case-insensitive, word boundaries.

**A5. Technical identifiers that nothing detects - LEAK, VERIFIED** (`detectors/recognizers.py:48-70` has only IPv4, FQDN, email, IBAN and card)
- Unchanged: `password=Sup3rS3cret!`, `api_key: sk-ant-...`, `AKIAIOSFODNN7EXAMPLE`, `Server=sqlprd01;...;User Id=m3admin;Password=Winter2026!;`, `\\FILESRV01\Projects`, `C:\Users\<name>\...`, `/home/<name>`, single-label hosts `SRVM3PRD01` and `m3be-prd-01`, URL query values (`?user=jdoe&token=abc123`). A JWT is only partly replaced.
- Fix: recognizers at score 0,9 or higher for key=value secrets (tokenize the value only), connection-string keys, JWT `\beyJ[\w-]+\.[\w-]+\.[\w-]+\b`, AWS `AKIA[0-9A-Z]{16}`, PEM private keys, vendor key prefixes, UNC host, `[A-Z]:\\Users\\([^\\\s]+)`, `/home/([^/\s]+)`, URL query values for user, email, token and key, and a configurable naming pattern for single-label hosts.

**A6. German PII gaps; language is fixed to "en" - LEAK, VERIFIED** (`core/types.py:47`; neither CLI nor UI sets the language)
- `Musterstraße 12, 10115 Berlin` becomes `Musterstraße 12, 10115 [LOCATION_2]`.
- `Steuer-ID 12 345 678 901` is PHONE at 0,40 (review band only). `SV-Nr 65 170839 J 003` is not found.
- `+49 511 1234567`, `0151 12345678` and `(0511) 123 45 67` are PHONE at 0,40, review band only, so they leak in CLI quick_review and in auto_skip. "Tel" gives no context boost.
- `Geburtsdatum: 01.02.1980` is DATE_TIME at 0,60 (review only).
- Fix: add `de_core_news_lg` as a second language. Add regexes for German phone numbers, street + number, postal code + city, Steuer-ID, SV-Nr and Personalausweis. Add the context words Tel, Telefon, Mobil, Handy and Fax.

**A7. Hostnames are never auto-redacted - LEAK, VERIFIED** (FQDN score 0,6 at `recognizers.py:58` is below `high_threshold` 0,65)
- The CLI default is quick_review with no reviewer, so every FQDN stays in clear text and the residual net reports 0.
- Fix: first make FQDN precise (B7). Then give 0,85 to internal suffixes (.local, .corp, .lan, .intern) and to public suffixes that tldextract validates.

**A8. Overlap resolution lets a short high-score span win, so the rest leaks - LEAK, VERIFIED** (`detectors/engine.py:45-78`)
- Deny list "Jane" (1,0) on "Jane Doe" gives `[TERM_5] Doe`.
- IPv6 `2001:db8:85a3::8a2e:370:7334` gives `[DATE_TIME_1]:db8:85a3::8a2e:370:7334` (DATE_TIME "2001" 0,85 beats IP 0,6).
- `url https://x.corp.local/a?u=jdoe` gives `[URL_1]rp.local/a?u=jdoe`.
- Fix: when spans overlap or one contains the other, keep the union. A leak is worse than a wrong token type. Add these 3 cases as tests.

**A9. GLiNER mode drops Presidio's pattern recognizers - LEAK, VERIFIED** (`engine.py:81-97`)
- Not found in the regex-only path: IPv6, MAC, `+49 511 1234567`, a spaced IBAN, `23.11.2026`. GLiNER also missed the spaced IBAN and the IPv6.
- Fix: also run Presidio's predefined pattern recognizers in GLiNER mode. They need no spaCy NER.

**A10. The residual safety net checks only IPv4 and email - LEAK, VERIFIED** (`core/residual.py:4-7`)
- After a quick_review run that left a host, a URL user and an IBAN, it returned `[]`. For A2 it reported 0 while the XML held the PII.
- Fix, in order: (1) scan the output for every mapping value (case-insensitive, word boundary); (2) add IPv6, MAC, IBAN with checksum, JWT and key prefixes; (3) scan the written file (all XML parts), not the extracted fragments.

**A11. Skipped files stay in the folder with their PII - LEAK (process), VERIFIED** (`io/text.py:5` reads UTF-8 only)
- A cp1252 file is skipped with "'utf-8' codec can't decode byte 0xfc" and stays untouched. Unsupported types (pdf, msg, eml, sql, env) also stay. In in-place mode the folder then mixes anonymized and original files.
- Fix: detect BOM, fall back to cp1252 and write back in the same encoding. Add .sql, .env, .conf, .toml, .tsv, .properties, .bat, .cs and .eml. Do not copy skipped files in output mode. In in-place mode give a loud "N files NOT anonymized" status and a non-zero exit code.

## B. Wrong output

**B1. docx hyperlink text is duplicated and grows on each round trip - WRONG OUTPUT + LEAK, VERIFIED** (`io/docx.py:17-23`)
- In python-docx 1.2, `paragraph.text` includes hyperlink text but `paragraph.runs` does not.
- After anonymize: `'Mail: [EMAIL_1] please.jane.doe@example.com'`. After de-anonymize: three copies of the email.
- Fix: use `iter_inner_content()` / `Hyperlink.runs`, or all `w:r` descendants. Rewrite the rels target.

**B2. Paragraph formatting collapses to the first run - WRONG OUTPUT, VERIFIED** (`io/docx.py:17-23`, `io/pptx.py:33-37`)
- Bold, plain and italic runs become one bold run. It stays bold after de-anonymize. Same in pptx.
- Fix: replace per run. Put the token in the first run the entity touches and remove only the covered characters from the other runs.

**B3. xlsx text cells that start with "=" become formulas - WRONG OUTPUT, VERIFIED** (`io/xlsx.py:29-30`)
- `'=== Contact jane.doe@... ==='` changes from type s to type f. `'=SUM is a word here'` also becomes a formula.
- Fix: write only the cells that changed and restore `data_type = "s"`.

**B4. A literal token in the source text is "restored" to real PII - WRONG OUTPUT, VERIFIED** (`core/anonymize.py:7`, `:19-39`)
- `Our template uses [PERSON_1] as placeholder. Contact Jane Doe.` de-anonymizes to `Our template uses Jane Doe as placeholder...`.
- Fix: detect token-shaped text during the scan and warn, or make tokens unique per mapping (for example `[PERSON_1_k7]`).

**B5. Some entity types produce tokens that cannot be restored - WRONG OUTPUT, VERIFIED** (`detectors/normalize.py:8-9`; token regex `\[[A-Z_]+_\d+\]` in `anonymize.py:7` and `residual.py:8`)
- GLiNER labels "e-mail", "ipv4 address", "Ärztin" and "steuer-id" give `[E-MAIL_1]`, `[IPV4_ADDRESS_1]`, `[ÄRZTIN_1]`, `[STEUER-ID_1]`, which de-anonymize neither restores nor counts as unknown.
- Fix: transliterate the label, map every character outside A-Z0-9 to `_`, and use `\[[A-Z][A-Z0-9_]*_\d+\]` in both places.

**B6. De-anonymize misses common AI rewrites and does not report them - WRONG OUTPUT, VERIFIED**
- Restored: `[PERSON_1]'s`, `**[PERSON_1]**`, `` `[IP_1]` ``.
- Not restored and not reported: `PERSON_1`, `[Person_1]`, `[PERSON 1]`, `[ PERSON_1 ]`, `\[PERSON\_1\]`, `[PERSON-1]`, `【PERSON_1】`. Only `[PERSON_01]` is counted as unknown.
- Fix: a second, tolerant pass that uses the mapping's own types, is case-insensitive and accepts optional brackets, escapes and `_`/space/`-` separators. Report every near-miss that was not restored.

**B7. Recognizers that destroy useful content - WRONG OUTPUT, VERIFIED** (`engine.py:17-22` loads all predefined recognizers with no `entities=` filter)
- `ticket CS00000001` becomes `[MEDICAL_LICENSE_1]1` (partial span). "German"/"French" become NRP. "Monday", "2026", "today" become DATE_TIME. `Ruf mich`, `Geburtsdatum`, `ping` become PERSON. "Personalausweis" becomes LOCATION, T22000129 becomes US_PASSPORT. `README.md`, `config.yaml`, `report.docx`, `os.path.join`, `self.value` become HOST (review band). `version 1.0.0.1` and `build 10.0.2.15` become IP (auto band).
- Fix: pass an explicit entity list to the analyzer; drop MEDICAL_LICENSE, US_*, NRP and UK_NHS; make DATE_TIME review-only or full dates only. For FQDN, reject file-extension TLDs and require a public suffix or a configured internal suffix. Lower the IPv4 score when "version" or "build" is the context.

**B8. The deny list matches inside words and splits case variants - WRONG OUTPUT, VERIFIED** (`recognizers.py:80`)
- Deny list "Jane" and "Ann" gives `[TERM_5] Doe and [TERM_5]t from [TERM_4]ual pl[TERM_3]ing. ...`.
- Fix: put `(?<!\w)...(?!\w)` around each term by default and sort the terms longest first.

## C. Quality

**C1. One real value gets many tokens - QUALITY, VERIFIED** (`core/mapping.py:17-25` uses the exact (type, text) as the key)
- The same email in lower and upper case gets two tokens. "Jane Doe", "Jane" and "Bold Jane Doe" get 3 PERSON tokens (spaCy took "Bold" from the run in front).
- Fix: casefold the key for EMAIL, HOST and URL, collapse whitespace, keep the first surface form for restore. Link name parts to the full name in the batch.

**C2. Mapping file security - QUALITY (security), code-verified**
- Default is plaintext JSON that lists every original value (`mapping.py:53-55`).
- PBKDF2-SHA256 with 200.000 iterations (`:9`). OWASP 2023 recommends 600.000; scrypt or Argon2id is better. The header `TANON1` stores no KDF parameters.
- `write_bytes` is not atomic. A crash during the write truncates the only key.
- `--passphrase` on the command line (`cli.py:34`, `:49`) ends up in shell history and the process list.
- Fix: temp file plus `os.replace`; scrypt or 600.000 iterations with KDF parameters in a `TANON2` header; getpass or an environment variable for the passphrase; encrypt by default or warn when the mapping is plaintext.

**C3. Tokens are numbered in reverse document order - NIT, VERIFIED** (`anonymize.py:13-16`): `a@b.de c@d.de e@f.de` gives `[EMAIL_3] [EMAIL_2] [EMAIL_1]`. Fix: assign tokens in ascending order, then replace right to left.

**C4. One value with two types gets two tokens - NIT, code-verified.**

**C5. The openpyxl round trip may drop content - QUALITY, SUSPECTED.** openpyxl can drop shapes, images and charts; `rich_text=False` flattens rich text; every string cell is rewritten even when unchanged. Fix: write only changed cells; add a fidelity test with a chart, an image and a rich-text cell.

## D. Checked, no defect found

- Chunk boundaries in Presidio mode: IP, email, IBAN, name and card placed across the 4.000 cut and the 3.800 window start at every offset. Every case gave one full span.
- AES-GCM encryption (random salt and nonce, clean wrong-passphrase error), the overwrite guard in `load_or_new`, and the round trip of UTF-8 BOM files and line endings.

## Suggested order

1. A1.
2. A2 + A3 + B1 together, with the generic unzip-and-grep test.
3. A10 step 1 + A4.
4. A8 + B8.
5. A5, A6, A7, A9, then B7.
6. B2-B6, then C.

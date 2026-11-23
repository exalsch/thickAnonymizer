# PII detector research for thickanon (as of 23.11.2026)

Reviewer: a Claude Code subagent. No repository file was changed. Benchmark scripts and downloaded models were kept in the session scratchpad only (`testset.py`, `ort_gliner.py`, `bench_*.py`, `speed*.py`, `score.py`).

## 1. Recommendation

**Keep the model and drop torch.** Run the same model that GLiNER mode uses today, `urchade/gliner_multi_pii-v1`, as the fp32 ONNX export `onnx-community/gliner_multi_pii-v1` / `onnx/model.onnx`, with a small runner on `onnxruntime` + `tokenizers` (about 130 lines). Also:
- Add 4 labels: `hostname`, `username`, `ip address`, `url`.
- Window the GLiNER input by about 100 words.
- Add an allow list for M3 program IDs and product names.

Why:
- **Same detections as today, without torch (MEASURED).** On the test set the torch-free runner gives exactly the same entities as `gliner` + torch.
- **Exe size.** torch, transformers and gliner leave the build; only `onnxruntime` (about 45 MB) and `tokenizers` (about 7,5 MB) are added. GLiNER mode can ship in the default exe at about 0,5 GB instead of about 3 GB. The model (1,16 GB) still downloads on first use.
- **Better recall for M3 text (MEASURED).** With the extra labels recall goes from 85,4 % to 93,9 % and precision from 85,1 % to 86,8 %. Usernames 5/11 -> 9/11, hosts 8/10 -> 10/10. The default Presidio + spaCy path finds only 62,2 % (3/15 companies, 1/11 usernames).
- **Bug in the current GLiNER path (MEASURED).** `gliner` truncates every input at 384 words (`max_len`) and only warns. thickanon sends 4.000-character chunks, so the end of each chunk is never scanned. On a 20.982-character document recall falls to 50,0 % (prod labels). Window size vs long-doc recall: 384 words 81,3 %, 250 words 81,9 %, 96 words (step 64) 89,0 %.
- **Speed is not a win.** GLiNER on mdeberta-v3-base is equally slow with torch or ONNX (4.949 vs 4.809 ms per 1.000 chars) and about 28x slower than Presidio + spaCy.

**Fast alternative:** `bardsai/eu-pii-anonimization-multilang-v3`. INT8 ONNX, 309 MB, token classification, Apache-2.0, 24 EU languages. About 3,3x faster than GLiNER. Recall 78,0 %, precision 84,3 %, but weak on usernames (2/11) and companies (9/15).

**Watch list:** `fastino/gliner2-privacy-filter-PII-multi` (GLiNER2-PII). Best recall (95,1 %, 11/11 usernames, 91,3 % on the long document), lower precision (83,0 %), slowest model. Its only torch-free runtime, `gliner2-onnx`, is experimental (2 commits, no release). Re-evaluate in 2027.

**Do not use:**
- `onnx-community` `model_int8.onnx` or any dynamic int8 quantization of the mdeberta GLiNER: 25,6 % recall, regex hits only.
- `piiranha` (CC BY-NC-ND 4.0, no commercial use).
- `fast_gliner` 0.4.1: still no Windows wheel.

## 2. Comparison

| Candidate | Licence | Size | Languages | Entity types | onnxruntime without torch | Notes |
|---|---|---|---|---|---|---|
| Presidio + spaCy `en_core_web_lg` (current default) | MIT | 425 MB | English | PER/ORG/GPE/DATE + regex | n/a (CNN) | Mature. German text goes through an English model. |
| `urchade/gliner_multi_pii-v1` (current optional, torch) | Apache-2.0 | 1,16 GB | en, fr, de, es, pt, it | zero-shot | no | 04/2024 |
| Same, `onnx-community/gliner_multi_pii-v1` fp32 | Apache-2.0 | 1,16 GB | same | zero-shot | **yes** | **Recommended.** Identical to torch. |
| Same, `blinzl/gliner_multi_pii-v1-q8w` | Apache-2.0 | 395 MB | same | zero-shot | yes | Identical results, slower than fp32 on this CPU. Single uploader. |
| Same, `onnx-community` `model_int8.onnx` | Apache-2.0 | 349 MB | same | zero-shot | yes | **Broken.** |
| `knowledgator/gliner-pii-base-v1.0` (+ edge, small, large) | Apache-2.0 | base 197 MB quint8 | English encoders | 60+ | yes | PUBLISHED F1 81,0 %; MEASURED recall 70,7 %, weak on German names and companies. |
| `nvidia/gliner-PII` | NVIDIA Open Model License | 1,78 GB | English | 55+ | no ONNX | PUBLISHED strict F1 0,87 Nemotron-PII |
| `fastino/gliner2-privacy-filter-PII-multi` | Apache-2.0 | 1,23 GB | 7 incl. de | 42 incl. username, ip, password, api_key | experimental | 05/2026, PUBLISHED SPY F1 0,477 |
| `OpenMed/GLiNER2.5-PII-Multilingual-v1` | Apache-2.0 | 1,15 GB | 7 incl. de | 1 generic label | no | 08.11.2026 |
| `bardsai/eu-pii-anonimization-multilang-v3` | Apache-2.0 | 309 MB INT8 | 24 EU | 37 incl. IP, device id, account id, secret, URL | **yes** | 27.10.2026, mmBERT-base, 8.192-token context |
| `openai/privacy-filter` | Apache-2.0 | 2,8 GB; ONNX q4 0,9 GB | mainly English | 8 | ONNX in repo | 04/2026. No hostname or username class. |
| `OpenMed/privacy-filter-multilingual-v2` | Apache-2.0 | 2,8 GB | 16 incl. de | 54 | no | 05/2026 |
| `iiiorg/piiranha-v1` | CC BY-NC-ND 4.0 | 1,1 GB | 6 incl. de | 17 | - | Not commercial |
| `ai4privacy/llama-ai4privacy-multilingual-...-openpii` | MIT | 151 MB int8 | 8 incl. de | categorical | yes | Not tested |
| spaCy `de_core_news_lg` / `xx_ent_wiki_sm` | MIT | 541 MB / 11 MB | de / multi | PER, LOC, ORG, MISC | n/a | Needs per-text language detection |
| Small local LLMs (0,6B-4B GGUF) | various | 0,5-3 GB | - | free text | llama.cpp | Rejected in the 06/2026 spec |

## 3. Benchmark (MEASURED)

Test set: 36 invented sentences (18 English, 18 German: M3 tickets, mails, logs, connection strings), 82 gold entities (19 PERSON, 15 ORG, 10 LOCATION, 4 EMAIL, 4 PHONE, 5 IP, 10 HOST, 11 USERNAME, 2 URL, 2 IBAN). 20 M3 terms (MMS001, CRS610, M3 CE ...) are "keep", so masking them is a harmful false positive. Each system runs like thickanon: model + the regex layer of `recognizers.py` + overlap resolution, threshold 0,35. "prod" = today's 10 labels; "ext" = 11 labels including hostname, username, ip address, url, iban. Long doc = the set repeated 6 times, chunked at 4.000/200.

| System | Recall | Precision | F1 | FP | FP on M3 terms | Long-doc recall |
|---|---|---|---|---|---|---|
| Presidio + spaCy (default) | 62,2 % | 69,4 % | 65,6 % | 26 | 4 | 62,2 % |
| GLiNER torch, prod (current optional) | 85,4 % | 85,1 % | 85,2 % | 13 | 7 | **50,0 %** |
| GLiNER torch, ext | 93,9 % | 86,8 % | 90,2 % | 12 | 10 | 54,1 % |
| GLiNER ONNX fp32, ext, 384-word windows | 93,9 % | 86,8 % | 90,2 % | 12 | 10 | 81,3 % |
| GLiNER ONNX fp32, ext, 96-word windows | 93,9 % | 86,8 % | 90,2 % | 12 | 10 | **89,0 %** |
| GLiNER ONNX q8w, ext | 93,9 % | 86,8 % | 90,2 % | 12 | 10 | 81,1 % |
| GLiNER ONNX dynamic int8 | 25,6 % | 92,0 % | 40,1 % | 2 | 0 | 24,4 % |
| knowledgator gliner-pii-base quint8, ext | 70,7 % | 85,5 % | 77,4 % | 11 | 5 | 33,1 % |
| GLiNER2-PII ONNX, prod | 89,0 % | 78,4 % | 83,4 % | 22 | 11 | 80,5 % |
| GLiNER2-PII ONNX, ext | 95,1 % | 83,0 % | 88,6 % | 17 | 8 | 91,3 % |
| bardsai v3 INT8 | 78,0 % | 84,3 % | 81,0 % | 14 | 6 | 82,1 % |

Found per type:

| System | PER | ORG | LOC | EMAIL | PHONE | IP | HOST | USER | URL | IBAN |
|---|---|---|---|---|---|---|---|---|---|---|
| Presidio + spaCy | 18/19 | 3/15 | 6/10 | 4/4 | 4/4 | 5/5 | 8/10 | 1/11 | 0/2 | 2/2 |
| GLiNER prod | 18/19 | 15/15 | 10/10 | 3/4 | 4/4 | 5/5 | 8/10 | 5/11 | 0/2 | 2/2 |
| GLiNER ext | 18/19 | 15/15 | 10/10 | 4/4 | 4/4 | 5/5 | 10/10 | 9/11 | 0/2 | 2/2 |
| knowledgator base | 12/19 | 9/15 | 10/10 | 4/4 | 4/4 | 5/5 | 9/10 | 3/11 | 0/2 | 2/2 |
| GLiNER2-PII ext | 19/19 | 14/15 | 7/10 | 4/4 | 4/4 | 5/5 | 10/10 | 11/11 | 2/2 | 2/2 |
| bardsai v3 | 19/19 | 9/15 | 9/10 | 4/4 | 4/4 | 5/5 | 9/10 | 2/11 | 1/2 | 2/2 |

Recurring GLiNER false positives: CRS610, CRS620, MWS410, MMS001, M3 CE, M3 BE, MEC, ION, Infor, TRN, `grid.host`. An allow list removes most of them.

### Speed (MEASURED under heavy background load, use as ratios only)

Fastest of 5 rounds, 4 threads, raw model without regex.

| System | ms per 1.000 chars | vs GLiNER fp32 |
|---|---|---|
| Presidio + spaCy (full detect) | 169,9 | 28x faster |
| bardsai v3 INT8 ORT | 1.470,0 | 3,3x faster |
| knowledgator base quint8 ORT | 2.432,8 | 2,0x faster |
| **GLiNER urchade fp32 ORT (recommended)** | 4.808,7 | 1,0 |
| GLiNER urchade torch (current) | 4.949,1 | same |
| GLiNER2-PII fp32 ORT | 6.897,5 | 1,4x slower |

Model load: ONNX fp32 9 to 15 s, torch GLiNER 33 s, Presidio 6 s. The q8w file is slower than fp32 because onnxruntime 1.32 runs 8-bit `MatMulNBits` without a packed kernel.

## 4. Integration steps

1. New `src/thickanon/detectors/gliner_onnx.py`: `OrtGliner(model_dir, onnx_file, threads)` whose `predict_entities(text, labels, threshold)` returns the same dicts as `gliner.GLiNER`, so `gliner_detect` does not change. Window by about 96 words with overlap.
2. `gliner_model._build_model`: load `OrtGliner`; resolve the folder with `huggingface_hub.snapshot_download(repo, revision=<pinned sha>, allow_patterns=["gliner_config.json", "tokenizer.json", "onnx/model.onnx"])` or `cfg.model_path`. Keep the clear `RuntimeError` when `onnxruntime` is missing.
3. `core/types.py`: `DEFAULT_GLINER_MODEL_ID = "onnx-community/gliner_multi_pii-v1"`; add `onnx_file="onnx/model.onnx"` and `threads`; add `hostname`, `username`, `ip address`, `url` to the labels; consider `max_chunk_chars` of about 1.500.
4. `normalize.py`: add `"HOSTNAME": "HOST"`.
5. Allow list for M3 program IDs (`[A-Z]{3}\d{3}(MI)?`) and product names, applied before `_resolve_overlaps`.
6. `pyproject.toml`: replace the `gliner` extra with `onnx = ["onnxruntime", "tokenizers", "huggingface_hub"]`, or move these into the base dependencies.
7. `packaging/thickanon.spec`: `collect_all` onnxruntime and tokenizers unconditionally; keep torch, transformers and gliner excluded. Expect about +50 to 60 MB; verify with a build.
8. Tests: stub-session unit tests (feeds, windowing, offsets, greedy decode), a gated parity test, and the 36-sentence set as a regression benchmark.
9. Threads: `intra_op_num_threads` about half the physical cores, one session per process.

## 5. Sources

- https://huggingface.co/urchade/gliner_multi_pii-v1
- https://huggingface.co/onnx-community/gliner_multi_pii-v1
- https://huggingface.co/blinzl/gliner_multi_pii-v1-q8w
- https://huggingface.co/knowledgator/gliner-pii-base-v1.0
- https://huggingface.co/knowledgator/gliner-pii-edge-v1.0
- https://huggingface.co/nvidia/gliner-PII
- https://huggingface.co/fastino/gliner2-privacy-filter-PII-multi
- https://arxiv.org/abs/2605.09973
- https://huggingface.co/DanKau/gliner2-pii-onnx
- https://github.com/lmoe/gliner2-onnx
- https://huggingface.co/fastino/GLiNER2-Guardrails-PII-Multi
- https://huggingface.co/OpenMed/GLiNER2.5-PII-Multilingual-v1
- https://huggingface.co/bardsai/eu-pii-anonimization-multilang-v3
- https://openai.com/index/introducing-openai-privacy-filter/
- https://huggingface.co/openai/privacy-filter
- https://huggingface.co/OpenMed/privacy-filter-multilingual-v2
- https://huggingface.co/iiiorg/piiranha-v1-detect-personal-information
- https://huggingface.co/ai4privacy/llama-ai4privacy-multilingual-categorical-anonymiser-openpii
- https://huggingface.co/spacy/de_core_news_lg
- https://microsoft.github.io/presidio/samples/python/gliner
- https://pypi.org/project/fast-gliner/

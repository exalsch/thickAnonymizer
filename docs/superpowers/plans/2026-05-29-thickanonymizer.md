# thickAnonymizer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Windows tool (PyWebView desktop app + CLI) that mass-anonymizes files into readable consistent tokens and can de-anonymize AI output back to the originals via a reversible mapping.

**Architecture:** A pure-Python `core` (detection, mapping, anonymize/deanonymize, residual scan) with an `io` layer that reads/writes ordered text *fragments* per file format (so formatting is preserved). Files are processed in two phases — **detect** then **apply** — so a review step can sit between them. Thin CLI and PyWebView shells call the core.

**Tech Stack:** Python 3.11+, microsoft-presidio + spaCy, python-docx, openpyxl, python-pptx, cryptography, pywebview, PyInstaller, pytest.

**Key shared types (defined in Task 2, used everywhere):**
- `Entity(start: int, end: int, entity_type: str, score: float, text: str)` — a detected span within one fragment.
- `ReviewMode(Enum)` — `QUICK_REVIEW`, `AUTO_REDACT`, `AUTO_SKIP`.
- `AnonymizeConfig` — thresholds, mode, deny_list, language.
- `MappingStore` — bidirectional value↔token store. Methods: `token_for(value, entity_type) -> str`, `value_for(token) -> str | None`, `to_dict()`, classmethod `from_dict(d)`, `save(path, passphrase=None)`, classmethod `load(path, passphrase=None)`.

**IO contract (Task 12, implemented per format):** every format module exposes
`read_fragments(path) -> list[str]` (ordered text fragments) and
`write_fragments(path, fragments: list[str]) -> None` (writes them back in the same order).
Fragment index is the stable id linking detect → apply.

---

### Task 1: Project scaffold

**Files:**
- Create: `pyproject.toml`
- Create: `src/thickanon/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/test_smoke.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_smoke.py
import thickanon

def test_package_imports():
    assert hasattr(thickanon, "__version__")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_smoke.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'thickanon'`

- [ ] **Step 3: Create the package and config**

```toml
# pyproject.toml
[project]
name = "thickanon"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
  "presidio-analyzer",
  "presidio-anonymizer",
  "python-docx",
  "openpyxl",
  "python-pptx",
  "cryptography",
  "pywebview",
]

[project.optional-dependencies]
dev = ["pytest", "pyinstaller"]

[project.scripts]
thickanon = "thickanon.cli:main"

[tool.setuptools.packages.find]
where = ["src"]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"
```

```python
# src/thickanon/__init__.py
__version__ = "0.1.0"
```

```python
# tests/__init__.py
```

- [ ] **Step 4: Install editable + spaCy model, run test**

Run:
```
pip install -e ".[dev]"
python -m spacy download en_core_web_lg
pytest tests/test_smoke.py -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml src tests
git commit -m "chore: scaffold thickanon package"
```

---

### Task 2: Core types and config

**Files:**
- Create: `src/thickanon/core/__init__.py`
- Create: `src/thickanon/core/types.py`
- Test: `tests/core/test_types.py`
- Create: `tests/core/__init__.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/core/test_types.py
from thickanon.core.types import Entity, ReviewMode, AnonymizeConfig

def test_entity_fields():
    e = Entity(start=0, end=4, entity_type="PERSON", score=0.9, text="John")
    assert (e.start, e.end, e.entity_type, e.score, e.text) == (0, 4, "PERSON", 0.9, "John")

def test_review_modes_exist():
    assert {m.name for m in ReviewMode} == {"QUICK_REVIEW", "AUTO_REDACT", "AUTO_SKIP"}

def test_config_defaults():
    c = AnonymizeConfig()
    assert c.mode is ReviewMode.QUICK_REVIEW
    assert 0 < c.low_threshold <= c.high_threshold <= 1
    assert c.deny_list == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/core/test_types.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write implementation**

```python
# src/thickanon/core/types.py
from dataclasses import dataclass, field
from enum import Enum

@dataclass(frozen=True)
class Entity:
    start: int
    end: int
    entity_type: str
    score: float
    text: str

class ReviewMode(Enum):
    QUICK_REVIEW = "quick_review"   # gray band -> human review (default)
    AUTO_REDACT = "auto_redact"     # gray band -> anonymize automatically
    AUTO_SKIP = "auto_skip"         # gray band -> leave, rely on residual scan

@dataclass
class AnonymizeConfig:
    mode: ReviewMode = ReviewMode.QUICK_REVIEW
    # lean-safe: low threshold so we over-redact rather than miss
    low_threshold: float = 0.35    # below this: ignore entirely
    high_threshold: float = 0.65   # at/above this: auto-anonymize
    deny_list: list[str] = field(default_factory=list)
    language: str = "en"
```

`tests/core/__init__.py` is empty.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/core/test_types.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/thickanon/core tests/core
git commit -m "feat: core types and config"
```

---

### Task 3: Mapping store (bidirectional token allocation)

**Files:**
- Create: `src/thickanon/core/mapping.py`
- Test: `tests/core/test_mapping.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/core/test_mapping.py
from thickanon.core.mapping import MappingStore

def test_consistent_tokens():
    m = MappingStore()
    t1 = m.token_for("John Smith", "PERSON")
    t2 = m.token_for("John Smith", "PERSON")
    assert t1 == t2 == "[PERSON_1]"

def test_increments_per_type():
    m = MappingStore()
    assert m.token_for("10.0.0.1", "IP") == "[IP_1]"
    assert m.token_for("10.0.0.2", "IP") == "[IP_2]"
    assert m.token_for("John", "PERSON") == "[PERSON_1]"

def test_reverse_lookup():
    m = MappingStore()
    tok = m.token_for("db.acme.local", "HOST")
    assert m.value_for(tok) == "db.acme.local"
    assert m.value_for("[HOST_999]") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/core/test_mapping.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write implementation**

```python
# src/thickanon/core/mapping.py
class MappingStore:
    def __init__(self):
        self._value_to_token: dict[tuple[str, str], str] = {}
        self._token_to_value: dict[str, str] = {}
        self._counters: dict[str, int] = {}

    def token_for(self, value: str, entity_type: str) -> str:
        key = (entity_type, value)
        if key in self._value_to_token:
            return self._value_to_token[key]
        self._counters[entity_type] = self._counters.get(entity_type, 0) + 1
        token = f"[{entity_type}_{self._counters[entity_type]}]"
        self._value_to_token[key] = token
        self._token_to_value[token] = value
        return token

    def value_for(self, token: str) -> str | None:
        return self._token_to_value.get(token)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/core/test_mapping.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/thickanon/core/mapping.py tests/core/test_mapping.py
git commit -m "feat: bidirectional mapping store"
```

---

### Task 4: Mapping persistence + optional encryption

**Files:**
- Modify: `src/thickanon/core/mapping.py`
- Test: `tests/core/test_mapping_persist.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/core/test_mapping_persist.py
import pytest
from thickanon.core.mapping import MappingStore

def test_plaintext_roundtrip(tmp_path):
    m = MappingStore()
    m.token_for("John", "PERSON")
    p = tmp_path / "map.json"
    m.save(p)
    loaded = MappingStore.load(p)
    assert loaded.value_for("[PERSON_1]") == "John"
    assert loaded.token_for("John", "PERSON") == "[PERSON_1]"  # counter preserved

def test_encrypted_roundtrip(tmp_path):
    m = MappingStore()
    m.token_for("10.0.0.1", "IP")
    p = tmp_path / "map.enc"
    m.save(p, passphrase="hunter2")
    loaded = MappingStore.load(p, passphrase="hunter2")
    assert loaded.value_for("[IP_1]") == "10.0.0.1"

def test_wrong_passphrase_raises(tmp_path):
    m = MappingStore()
    m.token_for("10.0.0.1", "IP")
    p = tmp_path / "map.enc"
    m.save(p, passphrase="hunter2")
    with pytest.raises(ValueError):
        MappingStore.load(p, passphrase="wrong")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/core/test_mapping_persist.py -v`
Expected: FAIL — `AttributeError: ... has no attribute 'save'`

- [ ] **Step 3: Write implementation (append to mapping.py)**

```python
# add imports at top of src/thickanon/core/mapping.py
import base64
import json
import os
from pathlib import Path
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

_MAGIC = b"TANON1"  # encrypted-file marker

def _derive_key(passphrase: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=200_000)
    return kdf.derive(passphrase.encode("utf-8"))
```

```python
    # add these methods inside class MappingStore:
    def to_dict(self) -> dict:
        return {
            "counters": self._counters,
            "pairs": [
                {"type": t, "value": v, "token": self._value_to_token[(t, v)]}
                for (t, v) in self._value_to_token
            ],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "MappingStore":
        m = cls()
        m._counters = dict(d.get("counters", {}))
        for pair in d.get("pairs", []):
            t, v, tok = pair["type"], pair["value"], pair["token"]
            m._value_to_token[(t, v)] = tok
            m._token_to_value[tok] = v
        return m

    def save(self, path, passphrase: str | None = None) -> None:
        raw = json.dumps(self.to_dict()).encode("utf-8")
        path = Path(path)
        if passphrase is None:
            path.write_bytes(raw)
            return
        salt = os.urandom(16)
        nonce = os.urandom(12)
        key = _derive_key(passphrase, salt)
        ct = AESGCM(key).encrypt(nonce, raw, None)
        path.write_bytes(_MAGIC + salt + nonce + ct)

    @classmethod
    def load(cls, path, passphrase: str | None = None) -> "MappingStore":
        data = Path(path).read_bytes()
        if data[: len(_MAGIC)] == _MAGIC:
            if passphrase is None:
                raise ValueError("mapping is encrypted; passphrase required")
            body = data[len(_MAGIC):]
            salt, nonce, ct = body[:16], body[16:28], body[28:]
            key = _derive_key(passphrase, salt)
            try:
                raw = AESGCM(key).decrypt(nonce, ct, None)
            except Exception as exc:  # InvalidTag etc.
                raise ValueError("wrong passphrase or corrupt mapping") from exc
            return cls.from_dict(json.loads(raw))
        return cls.from_dict(json.loads(data))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/core/test_mapping_persist.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/thickanon/core/mapping.py tests/core/test_mapping_persist.py
git commit -m "feat: mapping persistence with optional AES-GCM encryption"
```

---

### Task 5: Custom regex recognizers (IP, FQDN, email, credit card, IBAN)

**Files:**
- Create: `src/thickanon/detectors/__init__.py`
- Create: `src/thickanon/detectors/recognizers.py`
- Test: `tests/detectors/test_recognizers.py`
- Create: `tests/detectors/__init__.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/detectors/test_recognizers.py
from thickanon.detectors.recognizers import custom_recognizers

def _find(text, want_label):
    types = set()
    for rec in custom_recognizers():
        for res in rec.analyze(text, entities=rec.supported_entities, nlp_artifacts=None):
            types.add(res.entity_type)
    return want_label in types

def test_detects_ipv4():
    assert _find("server at 10.20.30.40 is down", "IP")

def test_detects_fqdn():
    assert _find("connect to db01.prod.acme.local now", "HOST")

def test_detects_email():
    assert _find("mail me at jane.doe@acme.com", "EMAIL_ADDRESS")

def test_credit_card_luhn_pass():
    assert _find("card 4539578763621486 expires soon", "CREDIT_CARD")

def test_credit_card_luhn_reject():
    # not a valid Luhn number -> should NOT be flagged as credit card
    assert not _find("ref 4539578763621487 here", "CREDIT_CARD")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/detectors/test_recognizers.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write implementation**

```python
# src/thickanon/detectors/recognizers.py
from presidio_analyzer import Pattern, PatternRecognizer, EntityRecognizer, RecognizerResult

_IPV4 = r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b"
# FQDN: at least two dot-separated labels ending in a 2+ letter TLD
_FQDN = r"\b(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}\b"
_EMAIL = r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b"
_IBAN = r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b"

def _luhn_ok(number: str) -> bool:
    digits = [int(c) for c in number if c.isdigit()]
    if len(digits) < 13:
        return False
    total, parity = 0, len(digits) % 2
    for i, d in enumerate(digits):
        if i % 2 == parity:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0

class CreditCardRecognizer(EntityRecognizer):
    """Regex candidate + Luhn validation to cut false positives."""
    PATTERN = r"\b(?:\d[ -]?){13,19}\b"

    def __init__(self):
        super().__init__(supported_entities=["CREDIT_CARD"], name="LuhnCardRecognizer")

    def load(self):  # required hook, nothing to load
        pass

    def analyze(self, text, entities, nlp_artifacts=None):
        import re
        results = []
        for m in re.finditer(self.PATTERN, text):
            candidate = m.group()
            if _luhn_ok(candidate):
                results.append(
                    RecognizerResult("CREDIT_CARD", m.start(), m.end(), 0.9)
                )
        return results

def custom_recognizers() -> list:
    return [
        PatternRecognizer(
            supported_entity="IP",
            name="IpRecognizer",
            patterns=[Pattern("ipv4", _IPV4, 0.85)],
        ),
        PatternRecognizer(
            supported_entity="HOST",
            name="FqdnRecognizer",
            patterns=[Pattern("fqdn", _FQDN, 0.6)],
        ),
        PatternRecognizer(
            supported_entity="EMAIL_ADDRESS",
            name="EmailRecognizer",
            patterns=[Pattern("email", _EMAIL, 0.9)],
        ),
        PatternRecognizer(
            supported_entity="IBAN_CODE",
            name="IbanRecognizer",
            patterns=[Pattern("iban", _IBAN, 0.8)],
        ),
        CreditCardRecognizer(),
    ]
```

`tests/detectors/__init__.py` and `src/thickanon/detectors/__init__.py` are empty.

> Note: emails also match the FQDN pattern (domain part). Overlap resolution is handled in Task 7 (highest-score span wins). The FQDN recognizer purposely has a lower score (0.6) than email (0.9).

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/detectors/test_recognizers.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/thickanon/detectors tests/detectors
git commit -m "feat: custom regex recognizers for IP/FQDN/email/IBAN/credit-card"
```

---

### Task 6: Deny-list recognizer

**Files:**
- Modify: `src/thickanon/detectors/recognizers.py`
- Test: `tests/detectors/test_denylist.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/detectors/test_denylist.py
from thickanon.detectors.recognizers import deny_list_recognizer

def test_denylist_matches_exact_terms():
    rec = deny_list_recognizer(["Project Falcon", "acme"])
    res = rec.analyze("Project Falcon ships at acme next week",
                      entities=["DENY"], nlp_artifacts=None)
    matched = sorted(r.entity_type for r in res)
    assert matched == ["DENY", "DENY"]
    assert all(r.score >= 0.99 for r in res)

def test_denylist_empty_is_safe():
    rec = deny_list_recognizer([])
    assert rec.analyze("nothing here", entities=["DENY"], nlp_artifacts=None) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/detectors/test_denylist.py -v`
Expected: FAIL — `ImportError: cannot import name 'deny_list_recognizer'`

- [ ] **Step 3: Write implementation (append to recognizers.py)**

```python
import re as _re

def deny_list_recognizer(terms: list[str]) -> "EntityRecognizer":
    class _DenyRecognizer(EntityRecognizer):
        def __init__(self, terms):
            super().__init__(supported_entities=["DENY"], name="DenyListRecognizer")
            cleaned = [t for t in terms if t.strip()]
            self._regex = (
                _re.compile("|".join(_re.escape(t) for t in cleaned), _re.IGNORECASE)
                if cleaned else None
            )

        def load(self):
            pass

        def analyze(self, text, entities, nlp_artifacts=None):
            if self._regex is None:
                return []
            return [
                RecognizerResult("DENY", m.start(), m.end(), 1.0)
                for m in self._regex.finditer(text)
            ]

    return _DenyRecognizer(terms)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/detectors/test_denylist.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/thickanon/detectors/recognizers.py tests/detectors/test_denylist.py
git commit -m "feat: deny-list recognizer for org-specific terms"
```

---

### Task 7: Analyzer builder and detect()

**Files:**
- Create: `src/thickanon/detectors/engine.py`
- Test: `tests/detectors/test_engine.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/detectors/test_engine.py
from thickanon.core.types import AnonymizeConfig
from thickanon.detectors.engine import detect

def test_detect_returns_entities_with_text():
    cfg = AnonymizeConfig(deny_list=["Project Falcon"])
    text = "Project Falcon admin John Doe at 10.0.0.5 emailed jane@acme.com"
    ents = detect(text, cfg)
    labels = {e.entity_type for e in ents}
    assert {"DENY", "IP", "EMAIL_ADDRESS"} <= labels
    # every entity's text slice matches its offsets
    for e in ents:
        assert text[e.start:e.end] == e.text

def test_overlaps_resolved_highest_score_wins():
    # jane@acme.com: EMAIL (0.9) must beat FQDN-on-domain (0.6); no nested dupes
    ents = detect("contact jane@acme.com please", AnonymizeConfig())
    spans = [(e.start, e.end) for e in ents]
    assert len(spans) == len(set(spans))  # no duplicate/overlapping spans
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/detectors/test_engine.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write implementation**

```python
# src/thickanon/detectors/engine.py
from functools import lru_cache
from presidio_analyzer import AnalyzerEngine, RecognizerRegistry
from thickanon.core.types import AnonymizeConfig, Entity
from thickanon.detectors.recognizers import custom_recognizers

@lru_cache(maxsize=4)
def _base_analyzer(language: str) -> AnalyzerEngine:
    registry = RecognizerRegistry()
    registry.load_predefined_recognizers(languages=[language])
    for rec in custom_recognizers():
        registry.add_recognizer(rec)
    return AnalyzerEngine(registry=registry, supported_languages=[language])

def _resolve_overlaps(results) -> list:
    """Keep highest-score span; drop spans contained in / overlapping a kept one."""
    ordered = sorted(results, key=lambda r: (-r.score, r.start, -(r.end - r.start)))
    kept = []
    for r in ordered:
        if any(not (r.end <= k.start or r.start >= k.end) for k in kept):
            continue  # overlaps an already-kept higher-score span
        kept.append(r)
    return sorted(kept, key=lambda r: r.start)

def detect(text: str, config: AnonymizeConfig) -> list[Entity]:
    analyzer = _base_analyzer(config.language)
    from thickanon.detectors.recognizers import deny_list_recognizer
    ad_hoc = [deny_list_recognizer(config.deny_list)] if config.deny_list else []
    raw = analyzer.analyze(
        text=text, language=config.language, ad_hoc_recognizers=ad_hoc
    )
    raw = [r for r in raw if r.score >= config.low_threshold]
    resolved = _resolve_overlaps(raw)
    return [
        Entity(r.start, r.end, r.entity_type, r.score, text[r.start:r.end])
        for r in resolved
    ]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/detectors/test_engine.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/thickanon/detectors/engine.py tests/detectors/test_engine.py
git commit -m "feat: analyzer engine with overlap resolution and detect()"
```

---

### Task 8: Confidence banding and review-decision logic

**Files:**
- Create: `src/thickanon/core/decide.py`
- Test: `tests/core/test_decide.py`

Splits detected entities into three buckets per mode, returning the entities to apply now plus the ones needing review.

- [ ] **Step 1: Write the failing test**

```python
# tests/core/test_decide.py
from thickanon.core.types import Entity, AnonymizeConfig, ReviewMode
from thickanon.core.decide import partition

def _e(score): return Entity(0, 1, "PERSON", score, "x")

def test_quick_review_splits_gray_band():
    cfg = AnonymizeConfig(mode=ReviewMode.QUICK_REVIEW, low_threshold=0.35, high_threshold=0.65)
    high, gray = partition([_e(0.9), _e(0.5)], cfg)
    assert len(high) == 1 and len(gray) == 1

def test_auto_redact_applies_gray():
    cfg = AnonymizeConfig(mode=ReviewMode.AUTO_REDACT, low_threshold=0.35, high_threshold=0.65)
    apply_now, gray = partition([_e(0.9), _e(0.5)], cfg)
    assert len(apply_now) == 2 and gray == []

def test_auto_skip_drops_gray():
    cfg = AnonymizeConfig(mode=ReviewMode.AUTO_SKIP, low_threshold=0.35, high_threshold=0.65)
    apply_now, gray = partition([_e(0.9), _e(0.5)], cfg)
    assert len(apply_now) == 1 and gray == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/core/test_decide.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write implementation**

```python
# src/thickanon/core/decide.py
from thickanon.core.types import Entity, AnonymizeConfig, ReviewMode

def partition(entities: list[Entity], config: AnonymizeConfig) -> tuple[list[Entity], list[Entity]]:
    """Return (apply_now, needs_review).

    high band (score >= high_threshold) is always applied.
    gray band (low_threshold <= score < high_threshold) depends on mode:
      QUICK_REVIEW -> needs_review
      AUTO_REDACT  -> apply_now
      AUTO_SKIP    -> dropped
    (entities below low_threshold were already filtered out in detect()).
    """
    apply_now, needs_review = [], []
    for e in entities:
        if e.score >= config.high_threshold:
            apply_now.append(e)
        else:
            if config.mode is ReviewMode.QUICK_REVIEW:
                needs_review.append(e)
            elif config.mode is ReviewMode.AUTO_REDACT:
                apply_now.append(e)
            # AUTO_SKIP: drop
    return apply_now, needs_review
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/core/test_decide.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/thickanon/core/decide.py tests/core/test_decide.py
git commit -m "feat: confidence banding / review partition logic"
```

---

### Task 9: Apply tokens to text

**Files:**
- Create: `src/thickanon/core/anonymize.py`
- Test: `tests/core/test_anonymize_text.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/core/test_anonymize_text.py
from thickanon.core.types import Entity
from thickanon.core.mapping import MappingStore
from thickanon.core.anonymize import apply_tokens

def test_replaces_spans_with_consistent_tokens():
    text = "John met John at 10.0.0.1"
    ents = [
        Entity(0, 4, "PERSON", 0.9, "John"),
        Entity(9, 13, "PERSON", 0.9, "John"),
        Entity(17, 25, "IP", 0.9, "10.0.0.1"),
    ]
    m = MappingStore()
    out = apply_tokens(text, ents, m)
    assert out == "[PERSON_1] met [PERSON_1] at [IP_1]"

def test_unsorted_entities_handled():
    text = "a@b.com and 10.0.0.1"
    ents = [Entity(12, 20, "IP", 0.9, "10.0.0.1"), Entity(0, 7, "EMAIL_ADDRESS", 0.9, "a@b.com")]
    out = apply_tokens(text, ents, MappingStore())
    assert out == "[EMAIL_ADDRESS_1] and [IP_1]"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/core/test_anonymize_text.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write implementation**

```python
# src/thickanon/core/anonymize.py
from thickanon.core.types import Entity
from thickanon.core.mapping import MappingStore

def apply_tokens(text: str, entities: list[Entity], mapping: MappingStore) -> str:
    """Replace each entity span with a consistent token. Right-to-left so
    earlier offsets stay valid."""
    for e in sorted(entities, key=lambda x: x.start, reverse=True):
        token = mapping.token_for(e.text, e.entity_type)
        text = text[:e.start] + token + text[e.end:]
    return text
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/core/test_anonymize_text.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/thickanon/core/anonymize.py tests/core/test_anonymize_text.py
git commit -m "feat: apply consistent tokens to text spans"
```

---

### Task 10: De-anonymize text + round-trip

**Files:**
- Modify: `src/thickanon/core/anonymize.py`
- Test: `tests/core/test_deanonymize.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/core/test_deanonymize.py
from thickanon.core.types import Entity
from thickanon.core.mapping import MappingStore
from thickanon.core.anonymize import apply_tokens, deanonymize

def test_roundtrip_restores_original():
    text = "John at 10.0.0.1 mailed jane@acme.com"
    ents = [
        Entity(0, 4, "PERSON", 0.9, "John"),
        Entity(8, 16, "IP", 0.9, "10.0.0.1"),
        Entity(24, 38, "EMAIL_ADDRESS", 0.9, "jane@acme.com"),
    ]
    m = MappingStore()
    anon = apply_tokens(text, ents, m)
    assert deanonymize(anon, m) == text

def test_deanonymize_ignores_unknown_tokens():
    m = MappingStore()
    m.token_for("John", "PERSON")
    assert deanonymize("hi [PERSON_1] and [GHOST_9]", m) == "hi John and [GHOST_9]"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/core/test_deanonymize.py -v`
Expected: FAIL — `ImportError: cannot import name 'deanonymize'`

- [ ] **Step 3: Write implementation (append to anonymize.py)**

```python
import re as _re

_TOKEN_RE = _re.compile(r"\[[A-Z_]+_\d+\]")

def deanonymize(text: str, mapping: MappingStore) -> str:
    def repl(match):
        original = mapping.value_for(match.group())
        return original if original is not None else match.group()
    return _TOKEN_RE.sub(repl, text)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/core/test_deanonymize.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/thickanon/core/anonymize.py tests/core/test_deanonymize.py
git commit -m "feat: deanonymize text via reverse mapping"
```

---

### Task 11: Residual leak scan

**Files:**
- Create: `src/thickanon/core/residual.py`
- Test: `tests/core/test_residual.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/core/test_residual.py
from thickanon.core.residual import residual_scan

def test_flags_leftover_ip_and_email():
    findings = residual_scan("clean [PERSON_1] but 10.0.0.9 and bob@x.com slipped")
    types = {f.entity_type for f in findings}
    assert "IP" in types and "EMAIL_ADDRESS" in types

def test_ignores_tokens_themselves():
    assert residual_scan("all good [PERSON_1] [IP_2] [HOST_3]") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/core/test_residual.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write implementation**

```python
# src/thickanon/core/residual.py
import re
from thickanon.core.types import Entity

# high-precision patterns only — this is a safety net, not primary detection
_PATTERNS = {
    "IP": re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b"),
    "EMAIL_ADDRESS": re.compile(r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b"),
}
_TOKEN_RE = re.compile(r"\[[A-Z_]+_\d+\]")

def residual_scan(text: str) -> list[Entity]:
    # blank out tokens so we never re-flag our own placeholders
    masked = _TOKEN_RE.sub(lambda m: " " * len(m.group()), text)
    findings = []
    for label, pat in _PATTERNS.items():
        for m in pat.finditer(masked):
            findings.append(Entity(m.start(), m.end(), label, 1.0, m.group()))
    return findings
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/core/test_residual.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/thickanon/core/residual.py tests/core/test_residual.py
git commit -m "feat: residual leak scan safety net"
```

---

### Task 12: IO interface + text format

**Files:**
- Create: `src/thickanon/io/__init__.py`
- Create: `src/thickanon/io/text.py`
- Test: `tests/io/test_text.py`
- Create: `tests/io/__init__.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/io/test_text.py
from thickanon.io.text import read_fragments, write_fragments

def test_text_single_fragment_roundtrip(tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("hello 10.0.0.1 world", encoding="utf-8")
    frags = read_fragments(p)
    assert frags == ["hello 10.0.0.1 world"]
    write_fragments(p, ["hello [IP_1] world"])
    assert p.read_text(encoding="utf-8") == "hello [IP_1] world"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/io/test_text.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write implementation**

```python
# src/thickanon/io/text.py
from pathlib import Path

def read_fragments(path) -> list[str]:
    return [Path(path).read_text(encoding="utf-8")]

def write_fragments(path, fragments: list[str]) -> None:
    Path(path).write_text(fragments[0], encoding="utf-8")
```

`tests/io/__init__.py` and `src/thickanon/io/__init__.py` are empty.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/io/test_text.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/thickanon/io tests/io
git commit -m "feat: io contract + text reader/writer"
```

---

### Task 13: IO docx

**Files:**
- Create: `src/thickanon/io/docx.py`
- Test: `tests/io/test_docx.py`

Reads/writes one fragment per paragraph and per table cell, in a stable order. Replacing `paragraph.text` is done by writing into the first run and clearing the rest (preserves paragraph style; intra-paragraph run formatting on edited paragraphs is not preserved — acceptable for v1, caught by tests).

- [ ] **Step 1: Write the failing test**

```python
# tests/io/test_docx.py
from docx import Document
from thickanon.io.docx import read_fragments, write_fragments

def test_docx_fragment_roundtrip(tmp_path):
    p = tmp_path / "d.docx"
    doc = Document()
    doc.add_paragraph("Contact John at 10.0.0.1")
    doc.add_paragraph("Second line")
    doc.save(p)

    frags = read_fragments(p)
    assert frags == ["Contact John at 10.0.0.1", "Second line"]

    write_fragments(p, ["Contact [PERSON_1] at [IP_1]", "Second line"])
    reread = read_fragments(p)
    assert reread == ["Contact [PERSON_1] at [IP_1]", "Second line"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/io/test_docx.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write implementation**

```python
# src/thickanon/io/docx.py
from docx import Document

def _iter_paragraphs(doc):
    yield from doc.paragraphs
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                yield from cell.paragraphs

def read_fragments(path) -> list[str]:
    doc = Document(str(path))
    return [p.text for p in _iter_paragraphs(doc)]

def _set_paragraph_text(paragraph, new_text: str) -> None:
    if paragraph.runs:
        paragraph.runs[0].text = new_text
        for run in paragraph.runs[1:]:
            run.text = ""
    elif new_text:
        paragraph.add_run(new_text)

def write_fragments(path, fragments: list[str]) -> None:
    doc = Document(str(path))
    for paragraph, new_text in zip(_iter_paragraphs(doc), fragments):
        if paragraph.text != new_text:
            _set_paragraph_text(paragraph, new_text)
    doc.save(str(path))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/io/test_docx.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/thickanon/io/docx.py tests/io/test_docx.py
git commit -m "feat: docx fragment reader/writer"
```

---

### Task 14: IO xlsx

**Files:**
- Create: `src/thickanon/io/xlsx.py`
- Test: `tests/io/test_xlsx.py`

One fragment per non-empty **string** cell (formulas/numbers skipped), ordered by sheet → row → column.

- [ ] **Step 1: Write the failing test**

```python
# tests/io/test_xlsx.py
from openpyxl import Workbook, load_workbook
from thickanon.io.xlsx import read_fragments, write_fragments

def test_xlsx_string_cells_roundtrip(tmp_path):
    p = tmp_path / "s.xlsx"
    wb = Workbook(); ws = wb.active
    ws["A1"] = "John Doe"; ws["A2"] = 42; ws["A3"] = "10.0.0.1"
    wb.save(p)

    assert read_fragments(p) == ["John Doe", "10.0.0.1"]

    write_fragments(p, ["[PERSON_1]", "[IP_1]"])
    wb2 = load_workbook(p)
    assert wb2.active["A1"].value == "[PERSON_1]"
    assert wb2.active["A2"].value == 42
    assert wb2.active["A3"].value == "[IP_1]"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/io/test_xlsx.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write implementation**

```python
# src/thickanon/io/xlsx.py
from openpyxl import load_workbook

def _string_cells(wb):
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for cell in row:
                if isinstance(cell.value, str) and cell.value.strip():
                    yield cell

def read_fragments(path) -> list[str]:
    wb = load_workbook(str(path))
    return [cell.value for cell in _string_cells(wb)]

def write_fragments(path, fragments: list[str]) -> None:
    wb = load_workbook(str(path))
    for cell, new_text in zip(_string_cells(wb), fragments):
        cell.value = new_text
    wb.save(str(path))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/io/test_xlsx.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/thickanon/io/xlsx.py tests/io/test_xlsx.py
git commit -m "feat: xlsx fragment reader/writer"
```

---

### Task 15: IO pptx

**Files:**
- Create: `src/thickanon/io/pptx.py`
- Test: `tests/io/test_pptx.py`

One fragment per paragraph inside every text frame, ordered slide → shape → paragraph. Paragraph text is written into its first run, remaining runs cleared (same trade-off as docx).

- [ ] **Step 1: Write the failing test**

```python
# tests/io/test_pptx.py
from pptx import Presentation
from pptx.util import Inches
from thickanon.io.pptx import read_fragments, write_fragments

def test_pptx_roundtrip(tmp_path):
    p = tmp_path / "p.pptx"
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[5])
    box = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(4), Inches(1))
    box.text_frame.paragraphs[0].add_run().text = "John at 10.0.0.1"
    prs.save(p)

    assert read_fragments(p) == ["John at 10.0.0.1"]
    write_fragments(p, ["[PERSON_1] at [IP_1]"])
    assert read_fragments(p) == ["[PERSON_1] at [IP_1]"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/io/test_pptx.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write implementation**

```python
# src/thickanon/io/pptx.py
from pptx import Presentation

def _paragraphs(prs):
    for slide in prs.slides:
        for shape in slide.shapes:
            if shape.has_text_frame:
                yield from shape.text_frame.paragraphs

def _para_text(paragraph) -> str:
    return "".join(run.text for run in paragraph.runs)

def read_fragments(path) -> list[str]:
    prs = Presentation(str(path))
    return [_para_text(p) for p in _paragraphs(prs)]

def write_fragments(path, fragments: list[str]) -> None:
    prs = Presentation(str(path))
    for paragraph, new_text in zip(_paragraphs(prs), fragments):
        if _para_text(paragraph) == new_text:
            continue
        if paragraph.runs:
            paragraph.runs[0].text = new_text
            for run in paragraph.runs[1:]:
                run.text = ""
    prs.save(str(path))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/io/test_pptx.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/thickanon/io/pptx.py tests/io/test_pptx.py
git commit -m "feat: pptx fragment reader/writer"
```

---

### Task 16: IO registry / dispatch

**Files:**
- Create: `src/thickanon/io/registry.py`
- Test: `tests/io/test_registry.py`

Maps file extension → reader/writer module; raises a typed error for unsupported types so the orchestrator can skip+log.

- [ ] **Step 1: Write the failing test**

```python
# tests/io/test_registry.py
import pytest
from thickanon.io.registry import get_handler, UnsupportedFileType

def test_known_extensions():
    for ext in [".txt", ".md", ".csv", ".py", ".docx", ".xlsx", ".pptx"]:
        h = get_handler(f"file{ext}")
        assert hasattr(h, "read_fragments") and hasattr(h, "write_fragments")

def test_unsupported_raises():
    with pytest.raises(UnsupportedFileType):
        get_handler("photo.png")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/io/test_registry.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write implementation**

```python
# src/thickanon/io/registry.py
from pathlib import Path
from thickanon.io import text, docx, xlsx, pptx

class UnsupportedFileType(Exception):
    pass

_TEXT_EXTS = {".txt", ".md", ".csv", ".py", ".js", ".ts", ".json", ".yaml", ".yml",
              ".log", ".ini", ".cfg", ".html", ".xml", ".sh", ".ps1", ".java", ".go"}

def get_handler(path):
    ext = Path(path).suffix.lower()
    if ext in _TEXT_EXTS:
        return text
    if ext == ".docx":
        return docx
    if ext == ".xlsx":
        return xlsx
    if ext == ".pptx":
        return pptx
    raise UnsupportedFileType(ext)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/io/test_registry.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/thickanon/io/registry.py tests/io/test_registry.py
git commit -m "feat: io registry / extension dispatch"
```

---

### Task 17: Backup utility

**Files:**
- Create: `src/thickanon/core/backup.py`
- Test: `tests/core/test_backup.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/core/test_backup.py
from pathlib import Path
from thickanon.core.backup import backup_file

def test_backup_copies_preserving_relative_layout(tmp_path):
    root = tmp_path / "data"; (root / "sub").mkdir(parents=True)
    src = root / "sub" / "a.txt"; src.write_text("secret", encoding="utf-8")
    backup_root = tmp_path / ".backup"

    dest = backup_file(src, root, backup_root)

    assert dest == backup_root / "sub" / "a.txt"
    assert dest.read_text(encoding="utf-8") == "secret"
    assert src.exists()  # original untouched (copy, not move)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/core/test_backup.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write implementation**

```python
# src/thickanon/core/backup.py
import shutil
from pathlib import Path

def backup_file(src, root, backup_root) -> Path:
    src, root, backup_root = Path(src), Path(root), Path(backup_root)
    rel = src.relative_to(root)
    dest = backup_root / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    return dest
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/core/test_backup.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/thickanon/core/backup.py tests/core/test_backup.py
git commit -m "feat: backup utility preserving relative layout"
```

---

### Task 18: Audit report

**Files:**
- Create: `src/thickanon/core/report.py`
- Test: `tests/core/test_report.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/core/test_report.py
from thickanon.core.types import Entity
from thickanon.core.report import BatchReport

def test_report_counts_and_flags():
    r = BatchReport()
    r.record_file("a.txt", applied=[Entity(0,1,"PERSON",0.9,"x"), Entity(2,3,"IP",0.9,"y")],
                  flagged=[Entity(4,5,"PERSON",0.5,"z")], residual=[])
    r.record_skip("photo.png", "unsupported: .png")
    d = r.to_dict()
    assert d["totals"]["PERSON"] == 2  # 1 applied + 1 flagged counts toward found
    assert d["totals"]["IP"] == 1
    assert d["files"]["a.txt"]["flagged_count"] == 1
    assert d["skipped"] == {"photo.png": "unsupported: .png"}
    assert "PERSON" in r.summary()  # human-readable string
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/core/test_report.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write implementation**

```python
# src/thickanon/core/report.py
from collections import Counter

class BatchReport:
    def __init__(self):
        self.totals = Counter()
        self.files = {}
        self.skipped = {}
        self.residual_total = 0

    def record_file(self, path, applied, flagged, residual):
        for e in list(applied) + list(flagged):
            self.totals[e.entity_type] += 1
        self.residual_total += len(residual)
        self.files[str(path)] = {
            "applied_count": len(applied),
            "flagged_count": len(flagged),
            "residual_count": len(residual),
        }

    def record_skip(self, path, reason):
        self.skipped[str(path)] = reason

    def to_dict(self):
        return {
            "totals": dict(self.totals),
            "files": self.files,
            "skipped": self.skipped,
            "residual_total": self.residual_total,
        }

    def summary(self) -> str:
        lines = [f"Files processed: {len(self.files)}, skipped: {len(self.skipped)}"]
        for etype, n in sorted(self.totals.items()):
            lines.append(f"  {etype}: {n}")
        if self.residual_total:
            lines.append(f"  RESIDUAL LEAKS FLAGGED: {self.residual_total}")
        return "\n".join(lines)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/core/test_report.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/thickanon/core/report.py tests/core/test_report.py
git commit -m "feat: batch audit report"
```

---

### Task 19: Orchestrator (anonymize_batch / deanonymize_batch)

**Files:**
- Create: `src/thickanon/core/orchestrator.py`
- Test: `tests/core/test_orchestrator.py`

Wires everything: walk files → backup (optional) → per-fragment detect → partition → apply high+auto → residual scan → write → accumulate report; persist mapping. De-anonymize walks files and applies the reverse map.

- [ ] **Step 1: Write the failing test**

```python
# tests/core/test_orchestrator.py
from pathlib import Path
from thickanon.core.types import AnonymizeConfig, ReviewMode
from thickanon.core.mapping import MappingStore
from thickanon.core.orchestrator import anonymize_paths, deanonymize_paths

def test_anonymize_then_deanonymize_roundtrip(tmp_path):
    root = tmp_path
    f = root / "note.txt"
    f.write_text("Email jane@acme.com from host 10.0.0.5", encoding="utf-8")

    cfg = AnonymizeConfig(mode=ReviewMode.AUTO_REDACT)
    mapping = MappingStore()
    report = anonymize_paths([f], root, mapping, cfg)

    out = f.read_text(encoding="utf-8")
    assert "jane@acme.com" not in out and "10.0.0.5" not in out
    assert "[EMAIL_ADDRESS_1]" in out and "[IP_1]" in out
    assert report.totals["EMAIL_ADDRESS"] == 1

    deanonymize_paths([f], mapping)
    assert f.read_text(encoding="utf-8") == "Email jane@acme.com from host 10.0.0.5"

def test_unsupported_file_skipped(tmp_path):
    img = tmp_path / "pic.png"; img.write_bytes(b"\x89PNG")
    report = anonymize_paths([img], tmp_path, MappingStore(), AnonymizeConfig())
    assert str(img) in report.skipped

def test_backup_created_when_requested(tmp_path):
    f = tmp_path / "a.txt"; f.write_text("John here", encoding="utf-8")
    backup_root = tmp_path / ".backup"
    anonymize_paths([f], tmp_path, MappingStore(),
                    AnonymizeConfig(mode=ReviewMode.AUTO_REDACT), backup_root=backup_root)
    assert (backup_root / "a.txt").read_text(encoding="utf-8") == "John here"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/core/test_orchestrator.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write implementation**

```python
# src/thickanon/core/orchestrator.py
from pathlib import Path
from thickanon.core.types import AnonymizeConfig
from thickanon.core.mapping import MappingStore
from thickanon.core.decide import partition
from thickanon.core.anonymize import apply_tokens, deanonymize
from thickanon.core.residual import residual_scan
from thickanon.core.report import BatchReport
from thickanon.core.backup import backup_file
from thickanon.detectors.engine import detect
from thickanon.io.registry import get_handler, UnsupportedFileType

def anonymize_paths(paths, root, mapping: MappingStore, config: AnonymizeConfig,
                    backup_root=None, review_callback=None) -> BatchReport:
    """Anonymize files in place.

    review_callback(flagged: list[Entity], fragment_text, path) -> list[Entity]
    is called in QUICK_REVIEW mode to let a UI choose which gray-band entities to
    apply. If None, gray-band entities are NOT applied (safe default for headless).
    """
    report = BatchReport()
    for path in paths:
        path = Path(path)
        try:
            handler = get_handler(path)
        except UnsupportedFileType as exc:
            report.record_skip(path, f"unsupported: {exc}")
            continue

        if backup_root is not None:
            backup_file(path, root, backup_root)

        fragments = handler.read_fragments(path)
        new_fragments, applied_all, flagged_all, residual_all = [], [], [], []
        for frag in fragments:
            entities = detect(frag, config)
            apply_now, flagged = partition(entities, config)
            if flagged and review_callback is not None:
                approved = review_callback(flagged, frag, path)
                apply_now = apply_now + list(approved)
                flagged = [e for e in flagged if e not in approved]
            new_text = apply_tokens(frag, apply_now, mapping)
            residual = residual_scan(new_text)
            new_fragments.append(new_text)
            applied_all += apply_now
            flagged_all += flagged
            residual_all += residual
        handler.write_fragments(path, new_fragments)
        report.record_file(path, applied_all, flagged_all, residual_all)
    return report

def deanonymize_paths(paths, mapping: MappingStore) -> None:
    for path in paths:
        path = Path(path)
        try:
            handler = get_handler(path)
        except UnsupportedFileType:
            continue
        frags = handler.read_fragments(path)
        handler.write_fragments(path, [deanonymize(f, mapping) for f in frags])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/core/test_orchestrator.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/thickanon/core/orchestrator.py tests/core/test_orchestrator.py
git commit -m "feat: batch orchestrator for anonymize/deanonymize"
```

---

### Task 20: CLI

**Files:**
- Create: `src/thickanon/cli.py`
- Test: `tests/test_cli.py`

Two subcommands: `anonymize` and `deanonymize`. Expands directories recursively, writes/loads the mapping, prints the report summary.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli.py
from thickanon.cli import main

def test_cli_anonymize_and_deanonymize(tmp_path, capsys):
    f = tmp_path / "x.txt"
    f.write_text("ping 10.0.0.7", encoding="utf-8")
    mp = tmp_path / "map.json"

    rc = main(["anonymize", str(f), "--root", str(tmp_path),
               "--mapping", str(mp), "--mode", "auto_redact"])
    assert rc == 0
    assert "10.0.0.7" not in f.read_text(encoding="utf-8")
    assert mp.exists()
    out = capsys.readouterr().out
    assert "IP" in out

    rc = main(["deanonymize", str(f), "--mapping", str(mp)])
    assert rc == 0
    assert f.read_text(encoding="utf-8") == "ping 10.0.0.7"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write implementation**

```python
# src/thickanon/cli.py
import argparse
from pathlib import Path
from thickanon.core.types import AnonymizeConfig, ReviewMode
from thickanon.core.mapping import MappingStore
from thickanon.core.orchestrator import anonymize_paths, deanonymize_paths

def _expand(paths) -> list[Path]:
    out = []
    for p in paths:
        p = Path(p)
        out.extend(f for f in p.rglob("*") if f.is_file()) if p.is_dir() else out.append(p)
    return out

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="thickanon")
    sub = parser.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("anonymize")
    a.add_argument("paths", nargs="+")
    a.add_argument("--root", required=True)
    a.add_argument("--mapping", required=True)
    a.add_argument("--mode", choices=[m.value for m in ReviewMode], default="quick_review")
    a.add_argument("--deny", nargs="*", default=[])
    a.add_argument("--backup")
    a.add_argument("--passphrase")

    d = sub.add_parser("deanonymize")
    d.add_argument("paths", nargs="+")
    d.add_argument("--mapping", required=True)
    d.add_argument("--passphrase")

    ns = parser.parse_args(argv)

    if ns.cmd == "anonymize":
        cfg = AnonymizeConfig(mode=ReviewMode(ns.mode), deny_list=ns.deny)
        mapping = MappingStore()
        report = anonymize_paths(_expand(ns.paths), Path(ns.root), mapping, cfg,
                                 backup_root=Path(ns.backup) if ns.backup else None)
        mapping.save(ns.mapping, passphrase=ns.passphrase)
        print(report.summary())
        return 0

    mapping = MappingStore.load(ns.mapping, passphrase=ns.passphrase)
    deanonymize_paths(_expand(ns.paths), mapping)
    print("Deanonymized.")
    return 0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_cli.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/thickanon/cli.py tests/test_cli.py
git commit -m "feat: CLI anonymize/deanonymize commands"
```

---

### Task 21: PyWebView desktop UI (drag-and-drop)

**Files:**
- Create: `src/thickanon/ui/app.py`
- Create: `src/thickanon/ui/web/index.html`
- Create: `src/thickanon/ui/api.py`
- Test: `tests/ui/test_api.py`
- Create: `tests/ui/__init__.py`

The UI is a thin shell: a JS `Api` bridge exposes core functions; the HTML provides a drop zone, a mode selector, deny-list/backup/passphrase fields, a "Review flagged items" list, and Anonymize / Deanonymize buttons. Business logic stays in `api.py` (testable without a browser).

- [ ] **Step 1: Write the failing test (API layer only — no browser)**

```python
# tests/ui/test_api.py
from thickanon.ui.api import Api

def test_api_anonymize_reports_summary(tmp_path):
    f = tmp_path / "n.txt"; f.write_text("call 10.0.0.3", encoding="utf-8")
    api = Api()
    result = api.anonymize(
        files=[str(f)], root=str(tmp_path), mapping_path=str(tmp_path / "m.json"),
        mode="auto_redact", deny=[], backup_dir=None, passphrase=None,
    )
    assert result["ok"] is True
    assert "IP" in result["summary"]
    assert "10.0.0.3" not in f.read_text(encoding="utf-8")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/ui/test_api.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write the API bridge**

```python
# src/thickanon/ui/api.py
from pathlib import Path
from thickanon.core.types import AnonymizeConfig, ReviewMode
from thickanon.core.mapping import MappingStore
from thickanon.core.orchestrator import anonymize_paths, deanonymize_paths
from thickanon.cli import _expand

class Api:
    def anonymize(self, files, root, mapping_path, mode, deny, backup_dir, passphrase):
        try:
            cfg = AnonymizeConfig(mode=ReviewMode(mode), deny_list=deny or [])
            mapping = MappingStore()
            report = anonymize_paths(
                _expand(files), Path(root), mapping, cfg,
                backup_root=Path(backup_dir) if backup_dir else None,
            )
            mapping.save(mapping_path, passphrase=passphrase or None)
            return {"ok": True, "summary": report.summary(), "report": report.to_dict()}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def deanonymize(self, files, mapping_path, passphrase):
        try:
            mapping = MappingStore.load(mapping_path, passphrase=passphrase or None)
            deanonymize_paths(_expand(files), mapping)
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/ui/test_api.py -v`
Expected: PASS

- [ ] **Step 5: Write the window launcher + HTML (manual verification)**

```python
# src/thickanon/ui/app.py
import webview
from pathlib import Path
from thickanon.ui.api import Api

def run():
    html = Path(__file__).parent / "web" / "index.html"
    webview.create_window("thickAnonymizer", url=str(html), js_api=Api(),
                          width=900, height=680)
    webview.start()

if __name__ == "__main__":
    run()
```

```html
<!-- src/thickanon/ui/web/index.html -->
<!doctype html><html><head><meta charset="utf-8"><title>thickAnonymizer</title>
<style>
 body{font-family:system-ui;margin:0;padding:24px;background:#0f1115;color:#e6e6e6}
 #drop{border:2px dashed #556;border-radius:12px;padding:48px;text-align:center;color:#99a}
 #drop.over{border-color:#6cf;color:#cdf}
 label{display:block;margin:10px 0 4px}
 input,select{width:100%;padding:8px;background:#1b1e26;color:#e6e6e6;border:1px solid #333;border-radius:6px}
 button{margin-top:16px;padding:10px 18px;border:0;border-radius:8px;background:#3b82f6;color:#fff;cursor:pointer}
 #out{white-space:pre-wrap;margin-top:16px;background:#1b1e26;padding:12px;border-radius:8px}
 .row{display:flex;gap:12px}.row>div{flex:1}
</style></head><body>
 <h2>thickAnonymizer</h2>
 <div id="drop">Drag files here, or use the file dialog button below</div>
 <ul id="files"></ul>
 <div class="row">
   <div><label>Mode</label><select id="mode">
     <option value="quick_review">Quick review (default)</option>
     <option value="auto_redact">Automatic — over-redact</option>
     <option value="auto_skip">Automatic — skip uncertain</option>
   </select></div>
   <div><label>Root folder</label><input id="root" placeholder="C:\\data"></div>
 </div>
 <label>Mapping file</label><input id="mapping" placeholder="C:\\data\\mapping.json">
 <div class="row">
   <div><label>Deny-list (comma-separated)</label><input id="deny" placeholder="Project Falcon, acme"></div>
   <div><label>Backup folder (optional)</label><input id="backup" placeholder=".backup"></div>
 </div>
 <label>Passphrase (optional, encrypts mapping)</label><input id="pass" type="password">
 <div>
   <button onclick="run('anonymize')">Anonymize</button>
   <button onclick="run('deanonymize')" style="background:#10b981">Deanonymize</button>
 </div>
 <div id="out"></div>
<script>
 let picked = [];
 const drop = document.getElementById('drop');
 drop.addEventListener('dragover', e=>{e.preventDefault();drop.classList.add('over')});
 drop.addEventListener('dragleave', ()=>drop.classList.remove('over'));
 drop.addEventListener('drop', e=>{
   e.preventDefault(); drop.classList.remove('over');
   picked = [...e.dataTransfer.files].map(f=>f.path || f.name);
   document.getElementById('files').innerHTML = picked.map(p=>`<li>${p}</li>`).join('');
 });
 async function run(kind){
   const out = document.getElementById('out'); out.textContent = 'Working…';
   const mapping = document.getElementById('mapping').value;
   const pass = document.getElementById('pass').value;
   let res;
   if(kind==='anonymize'){
     res = await window.pywebview.api.anonymize(
       picked, document.getElementById('root').value, mapping,
       document.getElementById('mode').value,
       document.getElementById('deny').value.split(',').map(s=>s.trim()).filter(Boolean),
       document.getElementById('backup').value || null, pass);
   } else {
     res = await window.pywebview.api.deanonymize(picked, mapping, pass);
   }
   out.textContent = res.ok ? (res.summary || 'Done.') : ('Error: ' + res.error);
 }
</script></body></html>
```

- [ ] **Step 6: Manual verification**

Run: `python -m thickanon.ui.app`
Expected: a native window opens. Drag a `.txt` containing `10.0.0.1`, set Root + Mapping path, choose `Automatic — over-redact`, click **Anonymize**. Confirm the file's IP is replaced and the summary shows `IP: 1`. Click **Deanonymize** on the same file with the same mapping → original restored.

> Note: `event.dataTransfer.files[].path` is available in the pywebview/Edge-WebView2 runtime on Windows. If a future runtime hides full paths, fall back to pywebview's `create_file_dialog`; out of scope for v1.

- [ ] **Step 7: Commit**

```bash
git add src/thickanon/ui tests/ui
git commit -m "feat: pywebview desktop UI with drag-and-drop"
```

---

### Task 22: Packaging to .exe

**Files:**
- Create: `packaging/thickanon.spec`
- Create: `README.md`

- [ ] **Step 1: Write the PyInstaller spec**

```python
# packaging/thickanon.spec
# Build: pyinstaller packaging/thickanon.spec
from PyInstaller.utils.hooks import collect_all

datas, binaries, hiddenimports = [], [], []
for pkg in ["en_core_web_lg", "presidio_analyzer", "presidio_anonymizer"]:
    d, b, h = collect_all(pkg)
    datas += d; binaries += b; hiddenimports += h

# bundle the web UI
datas += [("src/thickanon/ui/web/index.html", "thickanon/ui/web")]

a = Analysis(["src/thickanon/ui/app.py"], pathex=["src"], datas=datas,
             binaries=binaries, hiddenimports=hiddenimports)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, name="thickAnonymizer",
          console=False)
```

- [ ] **Step 2: Write README with build + usage**

```markdown
# thickAnonymizer

Mass-anonymize files into readable tokens (`[PERSON_1]`, `[IP_1]`, `[HOST_1]`)
before using them with AI tools, then de-anonymize the AI's output back.

## Install (dev)
    pip install -e ".[dev]"
    python -m spacy download en_core_web_lg

## CLI
    thickanon anonymize C:\data --root C:\data --mapping C:\data\map.json --mode quick_review
    thickanon deanonymize C:\data --mapping C:\data\map.json

## Desktop app
    python -m thickanon.ui.app

## Build a Windows .exe
    pyinstaller packaging/thickanon.spec
    # dist/thickAnonymizer.exe
```

- [ ] **Step 3: Build and smoke-test the exe (manual)**

Run: `pyinstaller packaging/thickanon.spec`
Expected: `dist/thickAnonymizer.exe` launches the window and anonymizes a sample file.

- [ ] **Step 4: Commit**

```bash
git add packaging README.md
git commit -m "build: PyInstaller packaging + README"
```

---

## Self-review notes

- **Spec coverage:** desktop+CLI (T20–21), Presidio core (T7), tokens+mapping (T3–4, T9–10), regex recognizers incl. IP/FQDN (T5), deny-list (T6), lean-safe banding + 3 review modes (T8), residual scan (T11), audit report (T18), in-place format-preserving IO for txt/csv/code/docx/xlsx/pptx (T12–16), backup option default-off (T17), optional mapping encryption (T4), packaging (T22). All spec sections map to a task.
- **Type consistency:** `Entity`, `ReviewMode`, `AnonymizeConfig`, `MappingStore.token_for/value_for/save/load`, `read_fragments/write_fragments`, `anonymize_paths/deanonymize_paths` are used identically across tasks.
- **Known v1 limitations (documented in-task):** docx/pptx run-level formatting on *edited* paragraphs not preserved; entities spanning multiple runs may be missed by primary detection (residual scan is the backstop); PDF/OCR out of scope.

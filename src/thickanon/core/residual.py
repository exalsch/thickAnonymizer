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

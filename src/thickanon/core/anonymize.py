import re as _re
from collections import Counter

from thickanon.core.types import Entity
from thickanon.core.mapping import MappingStore

_TOKEN_RE = _re.compile(r"\[[A-Z_]+_\d+\]")


def apply_tokens(text: str, entities: list[Entity], mapping: MappingStore) -> str:
    """Replace each entity span with a consistent token. Right-to-left so
    earlier offsets stay valid."""
    for e in sorted(entities, key=lambda x: x.start, reverse=True):
        token = mapping.token_for(e.text, e.entity_type)
        text = text[:e.start] + token + text[e.end:]
    return text


def deanonymize_counted(text: str, mapping: MappingStore) -> tuple[str, int, Counter]:
    """Restore tokens and report what happened.

    Returns (new_text, tokens_restored, unknown_tokens). A token with no mapping
    entry is left verbatim and counted as unknown: it means the caller loaded
    the wrong mapping file, which used to fail silently.
    """
    restored = 0
    unknown: Counter = Counter()

    def repl(match):
        nonlocal restored
        token = match.group()
        original = mapping.value_for(token)
        if original is None:
            unknown[token] += 1
            return token
        restored += 1
        return original

    return _TOKEN_RE.sub(repl, text), restored, unknown


def deanonymize(text: str, mapping: MappingStore) -> str:
    return deanonymize_counted(text, mapping)[0]

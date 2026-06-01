import re as _re

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


def deanonymize(text: str, mapping: MappingStore) -> str:
    def repl(match):
        original = mapping.value_for(match.group())
        return original if original is not None else match.group()
    return _TOKEN_RE.sub(repl, text)

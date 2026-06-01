from thickanon.core.types import Entity
from thickanon.core.mapping import MappingStore


def apply_tokens(text: str, entities: list[Entity], mapping: MappingStore) -> str:
    """Replace each entity span with a consistent token. Right-to-left so
    earlier offsets stay valid."""
    for e in sorted(entities, key=lambda x: x.start, reverse=True):
        token = mapping.token_for(e.text, e.entity_type)
        text = text[:e.start] + token + text[e.end:]
    return text

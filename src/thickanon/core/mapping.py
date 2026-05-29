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

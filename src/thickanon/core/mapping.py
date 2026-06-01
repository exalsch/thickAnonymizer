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

"""Secret stores: the OS keychain on desktops, an AES-256-GCM file in containers.

Secrets never go into the database, the config file or logs. In containers the file key comes from a
Docker/compose secret; with secrets present but no key, the server version refuses to start. A `*_FILE` environment
variable (the Docker secrets convention) can point at a file holding one secret, read only when needed.
"""

import json
import os
import secrets
from pathlib import Path
from typing import Protocol

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from yuo.core.errors import StartupError

SERVICE = "yuo"


class SecretStore(Protocol):
    def get(self, name: str) -> str | None: ...
    def set(self, name: str, value: str) -> None: ...
    def delete(self, name: str) -> None: ...


class KeyringStore:
    """Desktop keychain via `keyring`. Never `keyrings.alt` (plain files)."""

    def __init__(self) -> None:
        import keyring

        backend = keyring.get_keyring()
        if type(backend).__module__.startswith("keyrings.alt") or "fail" in type(backend).__module__:
            raise StartupError("no secure OS keychain available; use the encrypted file store")
        self._k = keyring

    def get(self, name: str) -> str | None:
        return self._k.get_password(SERVICE, name)

    def set(self, name: str, value: str) -> None:
        self._k.set_password(SERVICE, name, value)

    def delete(self, name: str) -> None:
        self._k.delete_password(SERVICE, name)


class EncryptedFileStore:
    """All secrets in one JSON object, encrypted with AES-256-GCM; a fresh nonce on every write."""

    def __init__(self, path: Path, key: bytes) -> None:
        if len(key) != 32:
            raise StartupError("the secrets key must be 32 bytes")
        self.path = path
        self._aead = AESGCM(key)

    @classmethod
    def from_key_file(cls, path: Path, key_file: Path) -> EncryptedFileStore:
        raw = key_file.read_bytes().strip()
        return cls(path, bytes.fromhex(raw.decode()) if len(raw) == 64 else raw)

    def _load(self) -> dict[str, str]:
        if not self.path.exists():
            return {}
        blob = self.path.read_bytes()
        data: dict[str, str] = json.loads(self._aead.decrypt(blob[:12], blob[12:], b"yuo-secrets-v1"))
        return data

    def _save(self, data: dict[str, str]) -> None:
        nonce = secrets.token_bytes(12)
        blob = nonce + self._aead.encrypt(nonce, json.dumps(data).encode(), b"yuo-secrets-v1")
        tmp = self.path.with_suffix(".tmp")
        tmp.write_bytes(blob)
        tmp.chmod(0o600)
        tmp.replace(self.path)

    def get(self, name: str) -> str | None:
        return self._load().get(name)

    def set(self, name: str, value: str) -> None:
        self._save(self._load() | {name: value})

    def delete(self, name: str) -> None:
        data = self._load()
        data.pop(name, None)
        self._save(data)


class EnvFileStore:
    """Read-only: `YUO_SECRET_<NAME>_FILE` names a file holding the secret (Docker secrets, dev machines)."""

    def get(self, name: str) -> str | None:
        ref = os.environ.get(f"YUO_SECRET_{name.upper().replace('-', '_')}_FILE")
        return Path(ref).read_text(encoding="utf-8").strip() if ref else None

    def set(self, name: str, value: str) -> None:
        raise StartupError("secrets from files are read-only; change the file instead")

    def delete(self, name: str) -> None:
        raise StartupError("secrets from files are read-only")


class ChainStore:
    """First store that knows the secret wins; writes go to the first writable store."""

    def __init__(self, *stores: SecretStore) -> None:
        self.stores = stores

    def get(self, name: str) -> str | None:
        for s in self.stores:
            if (v := s.get(name)) is not None:
                return v
        return None

    def set(self, name: str, value: str) -> None:
        for s in self.stores:
            if not isinstance(s, EnvFileStore):
                s.set(name, value)
                return
        raise StartupError("no writable secret store")

    def delete(self, name: str) -> None:
        for s in self.stores:
            if not isinstance(s, EnvFileStore):
                s.delete(name)

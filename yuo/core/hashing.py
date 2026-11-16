"""Content hashes: SHA-256 of the RFC 8785 (JCS) canonical form, computed in Python only."""

import hashlib

import rfc8785


def canonical(value: object) -> bytes:
    """JSON values only; rfc8785 raises on anything else (and on integers beyond 2**53)."""
    return rfc8785.dumps(value)  # type: ignore[arg-type]


def content_hash(value: object) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def bytes_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

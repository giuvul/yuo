"""A software passkey (ES256, `none` attestation) that answers WebAuthn requests the way a browser would."""

import base64
import hashlib
import json
import os
import struct
from typing import Any

import cbor2
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class SoftKey:
    def __init__(self, origin: str) -> None:
        self.origin = origin
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.credential_id = os.urandom(16)
        self.count = 0

    def _client_data(self, kind: str, challenge: str, origin: str | None) -> bytes:
        return json.dumps(
            {"type": kind, "challenge": challenge, "origin": origin or self.origin, "crossOrigin": False}
        ).encode()

    def create(self, options: dict[str, Any], origin: str | None = None) -> dict[str, Any]:
        rp_hash = hashlib.sha256(options["rp"]["id"].encode()).digest()
        nums = self.key.public_key().public_numbers()
        cose = cbor2.dumps(
            {1: 2, 3: -7, -1: 1, -2: nums.x.to_bytes(32, "big"), -3: nums.y.to_bytes(32, "big")}
        )
        attested = bytes(16) + struct.pack(">H", len(self.credential_id)) + self.credential_id + cose
        auth_data = rp_hash + bytes([0x45]) + struct.pack(">I", self.count) + attested  # UP, UV, AT
        attestation = cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": auth_data})
        cid = b64(self.credential_id)
        return {
            "id": cid,
            "rawId": cid,
            "type": "public-key",
            "response": {
                "clientDataJSON": b64(self._client_data("webauthn.create", options["challenge"], origin)),
                "attestationObject": b64(attestation),
                "transports": ["internal"],
            },
            "clientExtensionResults": {},
        }

    def get(self, options: dict[str, Any], origin: str | None = None) -> dict[str, Any]:
        self.count += 1
        rp_hash = hashlib.sha256(options["rpId"].encode()).digest()
        auth_data = rp_hash + bytes([0x05]) + struct.pack(">I", self.count)  # UP, UV
        client = self._client_data("webauthn.get", options["challenge"], origin)
        signature = self.key.sign(auth_data + hashlib.sha256(client).digest(), ec.ECDSA(hashes.SHA256()))
        cid = b64(self.credential_id)
        return {
            "id": cid,
            "rawId": cid,
            "type": "public-key",
            "response": {
                "clientDataJSON": b64(client),
                "authenticatorData": b64(auth_data),
                "signature": b64(signature),
                "userHandle": None,
            },
            "clientExtensionResults": {},
        }

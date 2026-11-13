"""Encryption of linked-account tokens at rest (ADR 0006, decision 3).

AES-256-GCM with a random 96-bit nonce per value. The key ID is part of the
ciphertext (``v1.<key id>.<nonce>.<ciphertext>``, base64url), so keys can be
rotated: new values use the current key, old values stay readable while their
key is configured. The associated data binds a ciphertext to its user and
provider, so a token copied onto another account's row does not decrypt.

Keys come from configuration (``SONGNEXUS_TOKEN_KEYS``, a JSON object of key ID
to base64 32-byte key); in production that value lives in Secret Manager, never
in the database or the image.
"""

from __future__ import annotations

import base64
import binascii
import os
from collections.abc import Mapping
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_VERSION = "v1"
_KEY_BYTES = 32
_NONCE_BYTES = 12


class TokenCipherError(ValueError):
    """A key is malformed, missing, or a ciphertext does not decrypt."""


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def new_key() -> str:
    """Returns a fresh base64 key, for ``SONGNEXUS_TOKEN_KEYS``."""
    return base64.b64encode(os.urandom(_KEY_BYTES)).decode()


@dataclass(frozen=True)
class TokenCipher:
    """Encrypts and decrypts tokens with a set of keys, one of them current."""

    keys: Mapping[str, bytes]
    current: str

    @classmethod
    def from_config(cls, keys: Mapping[str, str], current: str) -> TokenCipher:
        """Builds a cipher from base64 keys.

        Raises:
            TokenCipherError: A key is not 32 bytes of base64, or ``current`` is missing.
        """
        decoded = {}
        for key_id, value in keys.items():
            if not key_id.isalnum():
                raise TokenCipherError(f"key ID {key_id!r} must be alphanumeric")
            try:
                raw = base64.b64decode(value, validate=True)
            except (binascii.Error, ValueError) as exc:
                raise TokenCipherError(f"key {key_id!r} is not base64") from exc
            if len(raw) != _KEY_BYTES:
                raise TokenCipherError(f"key {key_id!r} must be {_KEY_BYTES} bytes")
            decoded[key_id] = raw
        if current not in decoded:
            raise TokenCipherError(f"current key {current!r} is not configured")
        return cls(decoded, current)

    def encrypt(self, plaintext: str, *, context: str) -> str:
        """Returns the ciphertext of ``plaintext``, bound to ``context`` (user and provider)."""
        nonce = os.urandom(_NONCE_BYTES)
        sealed = AESGCM(self.keys[self.current]).encrypt(
            nonce, plaintext.encode(), context.encode()
        )
        return ".".join((_VERSION, self.current, _b64e(nonce), _b64e(sealed)))

    def decrypt(self, ciphertext: str, *, context: str) -> str:
        """Returns the plaintext.

        Raises:
            TokenCipherError: Unknown version or key, tampering, or a different context.
        """
        try:
            version, key_id, nonce, sealed = ciphertext.split(".")
        except ValueError as exc:
            raise TokenCipherError("malformed ciphertext") from exc
        if version != _VERSION or key_id not in self.keys:
            raise TokenCipherError(f"cannot decrypt with key {key_id!r}")
        try:
            plain = AESGCM(self.keys[key_id]).decrypt(_b64d(nonce), _b64d(sealed), context.encode())
        except (InvalidTag, binascii.Error, ValueError) as exc:
            raise TokenCipherError("ciphertext does not decrypt") from exc
        return plain.decode()

    def needs_rotation(self, ciphertext: str) -> bool:
        """True when the value was encrypted under a key other than the current one."""
        parts = ciphertext.split(".")
        return len(parts) != 4 or parts[1] != self.current  # noqa: PLR2004 - four fields

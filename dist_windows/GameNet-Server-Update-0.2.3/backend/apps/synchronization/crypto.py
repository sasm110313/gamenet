"""Cryptographic helpers for the cloud <-> edge channel.

Remote commands are signed asymmetrically: the cloud holds the Ed25519 private
key (encrypted at rest), the edge holds only the public key. A leaked edge
credential therefore cannot be used to forge commands *to other edges*, and the
cloud never stores an edge's plaintext API secret.
"""

from __future__ import annotations

import base64
import hashlib
import secrets

from cryptography.exceptions import InvalidSignature
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


def new_secret(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def hash_token(token: str) -> str:
    """High-entropy bearer tokens are hashed with SHA-256; PBKDF2 is for
    low-entropy human passwords, not 256-bit random secrets."""
    return hashlib.sha256(token.encode()).hexdigest()


def b64e(raw: bytes) -> str:
    return base64.b64encode(raw).decode()


def b64d(value: str) -> bytes:
    return base64.b64decode(value)


def _fernet() -> Fernet:
    if not settings.SECRET_KEY:
        raise ImproperlyConfigured("SECRET_KEY is required to protect command keys")
    key = HKDF(
        algorithm=hashes.SHA256(), length=32, salt=b"gamenet-command-key-v1", info=b"fernet"
    ).derive(settings.SECRET_KEY.encode())
    return Fernet(base64.urlsafe_b64encode(key))


def generate_command_keypair() -> tuple[str, str]:
    """Returns (public_key_b64, encrypted_private_key)."""
    private = Ed25519PrivateKey.generate()
    raw_private = private.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    public = private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return b64e(public), _fernet().encrypt(raw_private).decode()


def sign_command(encrypted_private_key: str, canonical_payload: bytes) -> str:
    raw = _fernet().decrypt(encrypted_private_key.encode())
    private = Ed25519PrivateKey.from_private_bytes(raw)
    return b64e(private.sign(canonical_payload))


def verify_command(public_key_b64: str, canonical_payload: bytes, signature_b64: str) -> bool:
    try:
        public = Ed25519PublicKey.from_public_bytes(b64d(public_key_b64))
        public.verify(b64d(signature_b64), canonical_payload)
        return True
    except (InvalidSignature, InvalidToken, ValueError, TypeError):
        return False

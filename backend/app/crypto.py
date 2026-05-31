import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import get_settings


def _key() -> bytes:
    raw = base64.b64decode(get_settings().vault_key)
    if len(raw) != 32:
        raise ValueError("VAULT_KEY must decode to 32 bytes")
    return raw


def encrypt(plaintext: str) -> tuple[bytes, bytes]:
    """Returns (ciphertext, nonce)."""
    nonce = os.urandom(12)
    ct = AESGCM(_key()).encrypt(nonce, plaintext.encode("utf-8"), associated_data=None)
    return ct, nonce


def decrypt(ciphertext: bytes, nonce: bytes) -> str:
    return AESGCM(_key()).decrypt(nonce, ciphertext, associated_data=None).decode("utf-8")

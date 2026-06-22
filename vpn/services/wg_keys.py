"""WireGuard key material.

WireGuard uses Curve25519 (X25519) keys encoded as base64. We generate them with
`cryptography` rather than shelling out to `wg genkey`, so key generation works
identically on the Linux server and on a Windows dev box. The output is
byte-for-byte compatible with WireGuard.
"""
import base64
import os

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)


def generate_private_key() -> str:
    """Return a new base64-encoded X25519 private key."""
    key = X25519PrivateKey.generate()
    raw = key.private_bytes(
        Encoding.Raw, PrivateFormat.Raw, NoEncryption()
    )
    return base64.b64encode(raw).decode()


def public_key_from_private(private_key_b64: str) -> str:
    """Derive the base64 public key for a base64 private key."""
    raw = base64.b64decode(private_key_b64)
    key = X25519PrivateKey.from_private_bytes(raw)
    pub = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return base64.b64encode(pub).decode()


def generate_keypair() -> tuple[str, str]:
    """Return (private_key, public_key) as base64 strings."""
    priv = generate_private_key()
    return priv, public_key_from_private(priv)


def generate_preshared_key() -> str:
    """Return a new base64-encoded 32-byte preshared key."""
    return base64.b64encode(os.urandom(32)).decode()


def is_valid_key(value: str) -> bool:
    """A WireGuard key is 32 bytes, i.e. 44 base64 chars ending in '='."""
    try:
        return len(base64.b64decode(value, validate=True)) == 32
    except Exception:
        return False

"""
Envelope encryption helpers for AutoFormFiller.

Architecture:
- Each document gets a unique Data Encryption Key (DEK)
- DEKs are encrypted by a Master Key Encryption Key (KEK)
- KEK is stored in environment / HashiCorp Vault (never in DB)
- Sensitive profile fields are encrypted with a derived field-level key

This provides: per-user/per-document key isolation, so a single
compromised key exposes only one user's data, not the whole vault.
"""

import os
import base64
import secrets
from typing import Optional
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from app.core.config import settings


def _get_kek() -> bytes:
    """Load the master Key Encryption Key from config."""
    kek_b64 = settings.KEK_BASE64
    if not kek_b64:
        # Development fallback — never use in production
        import warnings
        warnings.warn(
            "KEK_BASE64 not set — using insecure development key. "
            "Set KEK_BASE64 in production.",
            UserWarning,
            stacklevel=2,
        )
        kek_b64 = base64.b64encode(b"dev_kek_32_bytes_do_not_use_prod").decode()
    return base64.b64decode(kek_b64)


def generate_dek() -> bytes:
    """Generate a new 32-byte Data Encryption Key."""
    return secrets.token_bytes(32)


def wrap_dek(dek: bytes) -> str:
    """Encrypt a DEK with the KEK. Returns base64-encoded ciphertext."""
    kek = _get_kek()
    # Derive a Fernet key from KEK
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"autoformfiller_kek_salt_v1",
        iterations=100_000,
    )
    fernet_key = base64.urlsafe_b64encode(kdf.derive(kek))
    f = Fernet(fernet_key)
    return f.encrypt(dek).decode("utf-8")


def unwrap_dek(wrapped_dek: str) -> bytes:
    """Decrypt a wrapped DEK using the KEK."""
    kek = _get_kek()
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"autoformfiller_kek_salt_v1",
        iterations=100_000,
    )
    fernet_key = base64.urlsafe_b64encode(kdf.derive(kek))
    f = Fernet(fernet_key)
    return f.decrypt(wrapped_dek.encode("utf-8"))


def derive_field_key(dek: bytes, field_key: str) -> bytes:
    """Derive a field-specific encryption key from a DEK."""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=f"field:{field_key}".encode(),
        iterations=10_000,
    )
    return base64.urlsafe_b64encode(kdf.derive(dek))


def encrypt_field(value: str, dek: bytes, field_key: str = "generic") -> str:
    """Encrypt a profile field value. Returns base64-encoded ciphertext."""
    if not value:
        return ""
    key = derive_field_key(dek, field_key)
    f = Fernet(key)
    return f.encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_field(ciphertext: str, dek: bytes, field_key: str = "generic") -> str:
    """Decrypt a profile field value."""
    if not ciphertext:
        return ""
    key = derive_field_key(dek, field_key)
    f = Fernet(key)
    return f.decrypt(ciphertext.encode("utf-8")).decode("utf-8")


def encrypt_document_content(content: bytes, dek: bytes) -> bytes:
    """Encrypt document binary content with its DEK."""
    key = base64.urlsafe_b64encode(dek)
    f = Fernet(key)
    return f.encrypt(content)


def decrypt_document_content(encrypted_content: bytes, dek: bytes) -> bytes:
    """Decrypt document binary content."""
    key = base64.urlsafe_b64encode(dek)
    f = Fernet(key)
    return f.decrypt(encrypted_content)


# Sensitive field keys that should always be encrypted
SENSITIVE_FIELD_KEYS = {
    "aadhaar_number",
    "pan_number",
    "passport_number",
    "driving_license_number",
    "voter_id",
    "bank_account_number",
    "bank_ifsc",
    "dob",
    "annual_income",
    "disability_percentage",
    "mobile_number",
    "email",
}


def mask_field_value(field_key: str, value: str) -> str:
    """Return a masked version of a sensitive field for display."""
    if field_key == "aadhaar_number" and len(value) == 12:
        return f"XXXX-XXXX-{value[-4:]}"
    elif field_key == "pan_number" and len(value) == 10:
        return f"XXXXX{value[-5:]}"
    elif field_key == "bank_account_number":
        return f"XXXXXXXXXX{value[-4:]}" if len(value) >= 4 else "XXXXXXXXXX"
    elif field_key in {"dob"}:
        parts = value.split("-")
        if len(parts) == 3:
            return f"XXXX-XX-{parts[-1]}"
    elif field_key == "mobile_number":
        return f"XXXXXX{value[-4:]}" if len(value) >= 4 else "XXXXXXXX"
    return value[:2] + "*" * (len(value) - 4) + value[-2:] if len(value) > 4 else "****"

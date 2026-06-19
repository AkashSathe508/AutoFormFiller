"""Unit tests for profile field encryption round-trip (document DEK)."""

import sys
from pathlib import Path

# Repo layout: backend/tests -> backend -> AutoFormFiller
BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
sys.path.insert(0, str(BACKEND_ROOT))
sys.path.insert(0, str(REPO_ROOT))

from app.core.encryption import generate_dek, encrypt_field, decrypt_field, wrap_dek, unwrap_dek


def test_encrypt_decrypt_with_same_document_dek():
    """Merge encrypts with document DEK; read path must unwrap the same DEK."""
    dek = generate_dek()
    wrapped = wrap_dek(dek)

    plaintext = "Ananya Sharma"
    encrypted = encrypt_field(plaintext, dek, "full_name")

    recovered_dek = unwrap_dek(wrapped)
    decrypted = decrypt_field(encrypted, recovered_dek, "full_name")

    assert decrypted == plaintext


def test_sensitive_field_round_trip():
    dek = generate_dek()
    aadhaar = "234123412346"
    encrypted = encrypt_field(aadhaar, dek, "aadhaar_number")
    assert decrypt_field(encrypted, dek, "aadhaar_number") == aadhaar


def test_wrong_dek_fails_decrypt():
    dek_a = generate_dek()
    dek_b = generate_dek()
    encrypted = encrypt_field("secret", dek_a, "pan_number")
    try:
        decrypt_field(encrypted, dek_b, "pan_number")
        assert False, "Expected decryption to fail with wrong DEK"
    except Exception:
        pass

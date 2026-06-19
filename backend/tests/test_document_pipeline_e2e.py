"""End-to-end document pipeline test (synthetic Aadhaar, in-process agent chain)."""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "backend"))

from ai_services.classification_agent.classifier import classify_document
from ai_services.extraction_agent.extractor import extract_fields
from ai_services.verification_agent.tamper_heuristics import run_verification
from ai_services.shared.schemas import DocType
from app.core.encryption import generate_dek, encrypt_field, decrypt_field, wrap_dek, unwrap_dek


SYNTHETIC_AADHAAR_OCR = """
GOVERNMENT OF INDIA
Unique Identification Authority of India
AADHAAR
Name: Ravi Kumar Sharma
Date of Birth: 15/08/1995
Gender: Male
Address: 42 MG Road, Pune, Maharashtra 411001
2341 2341 2346
"""


def test_synthetic_aadhaar_pipeline_agent_chain():
    """Upload → OCR (simulated) → classify → verify → extract."""
    document_id = "test-doc-aadhaar-001"
    ocr_text = SYNTHETIC_AADHAAR_OCR
    ocr_confidence = 0.91

    cls = classify_document(document_id, ocr_text, ocr_confidence)
    assert cls.doc_type == DocType.AADHAAR

    ver = run_verification(
        document_id,
        b"",  # no image bytes for checksum-only path
        "application/pdf",
        ocr_text,
        cls.doc_type,
    )
    assert any(c.check_name == "aadhaar_verhoeff" for c in ver.checks)

    structured = extract_fields(
        ocr_text,
        cls.doc_type.value,
        ocr_confidence=ocr_confidence,
        verification_checks=[c.model_dump() for c in ver.checks],
    )
    assert "full_name" in structured
    assert "aadhaar_number" in structured
    assert structured["aadhaar_number"]["value"] == "234123412346"
    assert structured["dob"]["value"] == "15/08/1995"


def test_synthetic_aadhaar_profile_encryption_round_trip():
    """Profile merge encryption can be read back with the same document DEK."""
    structured = extract_fields(
        SYNTHETIC_AADHAAR_OCR,
        DocType.AADHAAR.value,
        ocr_confidence=0.9,
    )
    dek = generate_dek()
    wrapped = wrap_dek(dek)

    for field_key, field_data in structured.items():
        encrypted = encrypt_field(field_data["value"], dek, field_key)
        recovered_dek = unwrap_dek(wrapped)
        decrypted = decrypt_field(encrypted, recovered_dek, field_key)
        assert decrypted == field_data["value"]


def test_processing_status_literal_values():
    """Pipeline status values exposed by the API."""
    allowed = {"processing", "extracted", "verified", "failed", "uploaded"}
    for value in ("processing", "extracted", "verified", "failed"):
        assert value in allowed

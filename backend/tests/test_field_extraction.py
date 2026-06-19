"""Tests for document-type field extraction."""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from ai_services.extraction_agent.extractor import extract_fields
from ai_services.shared.schemas import DocType


SYNTHETIC_AADHAAR_OCR = """
GOVERNMENT OF INDIA
Unique Identification Authority of India
AADHAAR
Name: Ravi Kumar Sharma
Date of Birth: 15/08/1995
Gender: Male
Address: 42 MG Road, Pune, Maharashtra 411001
1234 5678 9012
"""


SYNTHETIC_PAN_OCR = """
INCOME TAX DEPARTMENT
GOVT. OF INDIA
Permanent Account Number
Name: RAVI KUMAR SHARMA
Father's Name: SHYAM LAL SHARMA
Date of Birth: 15/08/1995
ABCPF1234F
"""


def test_aadhaar_extraction_with_checksum_boost():
    fields = extract_fields(
        SYNTHETIC_AADHAAR_OCR,
        DocType.AADHAAR.value,
        ocr_confidence=0.9,
        verification_checks=[{"check_name": "aadhaar_verhoeff", "passed": True}],
    )
    assert "full_name" in fields
    assert "Ravi" in fields["full_name"]["value"]
    assert "aadhaar_number" in fields
    assert fields["aadhaar_number"]["value"] == "123456789012"
    assert fields["aadhaar_number"]["confidence"] >= 0.95
    assert fields["dob"]["value"] == "15/08/1995"
    assert fields["gender"]["value"] == "Male"


def test_pan_extraction():
    fields = extract_fields(
        SYNTHETIC_PAN_OCR,
        DocType.PAN.value,
        ocr_confidence=0.88,
        verification_checks=[{"check_name": "pan_format", "passed": True}],
    )
    assert fields["pan_number"]["value"] == "ABCPF1234F"
    assert fields["pan_number"]["confidence"] >= 0.95
    assert "father_name" in fields
    assert "SHYAM" in fields["father_name"]["value"]


def test_unknown_doc_type_falls_back_to_generic():
    text = "Name: Test User\n1234 5678 9012"
    fields = extract_fields(text, DocType.UNKNOWN.value)
    assert "full_name" in fields or "aadhaar_number" in fields

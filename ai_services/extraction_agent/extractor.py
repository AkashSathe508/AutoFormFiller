"""Document-type-specific field extraction from OCR text."""

import re
from typing import Any, Dict, List, Optional

from ai_services.shared.schemas import DocType
from ai_services.verification_agent.checksum_validators import (
    extract_aadhaar_number,
    extract_pan_number,
    verhoeff_validate,
    PAN_PATTERN,
)


def extract_fields(
    ocr_text: str,
    doc_type: str,
    ocr_confidence: float = 0.85,
    verification_checks: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Dict[str, Any]]:
    """
    Extract structured profile fields from OCR text.

    Returns: {field_key: {value, confidence}}
    """
    verification_checks = verification_checks or []
    check_passed = {
        c.get("check_name"): c.get("passed", False)
        for c in verification_checks
        if isinstance(c, dict)
    }

    doc_type_upper = (doc_type or DocType.UNKNOWN.value).upper()

    if doc_type_upper == DocType.AADHAAR.value:
        return _extract_aadhaar(ocr_text, ocr_confidence, check_passed)
    if doc_type_upper == DocType.PAN.value:
        return _extract_pan(ocr_text, ocr_confidence, check_passed)

    return _extract_generic(ocr_text, ocr_confidence)


def _field(value: str, confidence: float) -> Dict[str, Any]:
    return {"value": value, "confidence": round(min(max(confidence, 0.0), 1.0), 3)}


def _first_match(text: str, patterns: List[str], flags: int = re.MULTILINE | re.IGNORECASE) -> Optional[str]:
    for pattern in patterns:
        match = re.search(pattern, text, flags)
        if match:
            value = match.group(1).strip()
            if len(value) > 1:
                return value
    return None


def _extract_aadhaar(
    ocr_text: str,
    ocr_confidence: float,
    check_passed: Dict[str, bool],
) -> Dict[str, Dict[str, Any]]:
    fields: Dict[str, Dict[str, Any]] = {}
    base = max(ocr_confidence, 0.7)

    aadhaar = extract_aadhaar_number(ocr_text)
    if aadhaar:
        checksum_ok = verhoeff_validate(aadhaar) or check_passed.get("aadhaar_verhoeff", False)
        conf = 0.99 if checksum_ok else 0.78
        fields["aadhaar_number"] = _field(aadhaar, conf)

    name = _first_match(ocr_text, [
        r"(?:Name|NAME)\s*[:\-/]?\s*([A-Z][A-Za-z\s\.]{2,60})",
        r"\u0928\u093e\u092e\s*[:\-/]?\s*([\u0900-\u097F\s\.]{2,60})",
    ])
    if name:
        fields["full_name"] = _field(name, base * 0.95)

    dob = _first_match(ocr_text, [
        r"(?:Date of Birth|DOB|D\.O\.B\.?|Birth)[:\s]+(\d{2}[/\-]\d{2}[/\-]\d{4})",
        r"(?:Year of Birth)[:\s]+(\d{4})",
        r"(?:\u091c\u0928\u092e\s*\u0924\u093f\u0925\u093f)[:\s]+(\d{2}[/\-]\d{2}[/\-]\d{4})",
    ])
    if dob:
        fields["dob"] = _field(dob, base * 0.9)

    gender = _first_match(ocr_text, [
        r"(?:Gender|Sex)[:\s]+(Male|Female|Transgender|MALE|FEMALE|TRANSGENDER)",
    ])
    if gender:
        fields["gender"] = _field(gender.title(), base * 0.88)

    address = _first_match(ocr_text, [
        r"(?:Address|ADDR|\u092a\u0924\u093e)[:\s]+([\w\s,.\-/#'\u0900-\u097F]{10,250}?)(?:\n(?:Mobile|Phone|VID|\d{4}\s\d{4})|\Z)",
    ])
    if address:
        fields["address"] = _field(address.strip(), base * 0.82)

    return fields


def _extract_pan(
    ocr_text: str,
    ocr_confidence: float,
    check_passed: Dict[str, bool],
) -> Dict[str, Dict[str, Any]]:
    fields: Dict[str, Dict[str, Any]] = {}
    base = max(ocr_confidence, 0.7)

    pan = extract_pan_number(ocr_text)
    if pan:
        format_ok = bool(PAN_PATTERN.match(pan)) or check_passed.get("pan_format", False)
        conf = 0.98 if format_ok else 0.75
        fields["pan_number"] = _field(pan, conf)

    name = _first_match(ocr_text, [
        r"(?:Name|NAME|Applicant)[:\s]+([A-Z][A-Za-z\s\.]{2,60})",
    ])
    if name:
        fields["full_name"] = _field(name, base * 0.93)

    father = _first_match(ocr_text, [
        r"(?:Father['\u2019]s?\s*Name|Father)[:\s]+([A-Z][A-Za-z\s\.]{2,60})",
    ])
    if father:
        fields["father_name"] = _field(father, base * 0.9)

    dob = _first_match(ocr_text, [
        r"(?:Date of Birth|DOB)[:\s]+(\d{2}[/\-]\d{2}[/\-]\d{4})",
    ])
    if dob:
        fields["dob"] = _field(dob, base * 0.88)

    return fields


def _extract_generic(ocr_text: str, ocr_confidence: float) -> Dict[str, Dict[str, Any]]:
    """Fallback extraction for unknown document types."""
    fields: Dict[str, Dict[str, Any]] = {}
    base = max(ocr_confidence, 0.65)

    aadhaar = extract_aadhaar_number(ocr_text)
    if aadhaar:
        fields["aadhaar_number"] = _field(
            aadhaar,
            0.95 if verhoeff_validate(aadhaar) else 0.72,
        )

    pan = extract_pan_number(ocr_text)
    if pan and PAN_PATTERN.match(pan):
        fields["pan_number"] = _field(pan, 0.92)

    name = _first_match(ocr_text, [
        r"Name[:\s]+([A-Z][A-Za-z\s]{2,50})",
    ])
    if name:
        fields["full_name"] = _field(name, base * 0.85)

    return fields

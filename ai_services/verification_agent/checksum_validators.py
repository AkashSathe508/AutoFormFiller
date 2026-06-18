"""
Document checksum and format validators.
- Aadhaar: Verhoeff algorithm
- PAN: format/category code check
- Passport: MRZ ICAO-9303 check-digit validation
"""

import re
from typing import List, Tuple, Optional
from ai_services.shared.schemas import VerificationCheck


# ===== AADHAAR: VERHOEFF ALGORITHM =====

VERHOEFF_TABLE_D = [
    [0,1,2,3,4,5,6,7,8,9],
    [1,2,3,4,0,6,7,8,9,5],
    [2,3,4,0,1,7,8,9,5,6],
    [3,4,0,1,2,8,9,5,6,7],
    [4,0,1,2,3,9,5,6,7,8],
    [5,9,8,7,6,0,4,3,2,1],
    [6,5,9,8,7,1,0,4,3,2],
    [7,6,5,9,8,2,1,0,4,3],
    [8,7,6,5,9,3,2,1,0,4],
    [9,8,7,6,5,4,3,2,1,0],
]

VERHOEFF_TABLE_P = [
    [0,1,2,3,4,5,6,7,8,9],
    [1,5,7,6,2,8,3,0,9,4],
    [5,8,0,3,7,9,6,1,4,2],
    [8,9,1,6,0,4,3,5,2,7],
    [9,4,5,3,1,2,6,8,7,0],
    [4,2,8,6,5,7,3,9,0,1],
    [2,7,9,3,8,0,6,4,1,5],
    [7,0,4,6,9,1,3,2,5,8],
]

VERHOEFF_TABLE_INV = [0,4,3,2,1,9,8,7,6,5]


def verhoeff_validate(number: str) -> bool:
    """Validate an Aadhaar number using the Verhoeff algorithm."""
    digits = [int(d) for d in reversed(number.replace(' ', ''))]
    c = 0
    for i, digit in enumerate(digits):
        c = VERHOEFF_TABLE_D[c][VERHOEFF_TABLE_P[i % 8][digit]]
    return c == 0


def extract_aadhaar_number(ocr_text: str) -> Optional[str]:
    """Extract 12-digit Aadhaar number from OCR text."""
    # Match formats: XXXX XXXX XXXX or XXXXXXXXXXXX
    patterns = [
        r'\b(\d{4}\s\d{4}\s\d{4})\b',
        r'\b(\d{12})\b',
    ]
    for pattern in patterns:
        matches = re.findall(pattern, ocr_text)
        for match in matches:
            clean = match.replace(' ', '')
            if len(clean) == 12 and not clean.startswith('0'):
                return clean
    return None


def validate_aadhaar(ocr_text: str) -> VerificationCheck:
    """Run Aadhaar checksum validation."""
    number = extract_aadhaar_number(ocr_text)
    if number is None:
        return VerificationCheck(
            check_name="aadhaar_verhoeff",
            passed=False,
            detail="Could not extract a 12-digit Aadhaar number from document",
        )
    is_valid = verhoeff_validate(number)
    return VerificationCheck(
        check_name="aadhaar_verhoeff",
        passed=is_valid,
        detail=f"Aadhaar number {'passes' if is_valid else 'FAILS'} Verhoeff checksum validation",
    )


# ===== PAN CARD VALIDATION =====

PAN_PATTERN = re.compile(r'^[A-Z]{5}[0-9]{4}[A-Z]$')
PAN_CATEGORY_CODES = {
    'P': 'Individual',
    'C': 'Company',
    'H': 'HUF (Hindu Undivided Family)',
    'F': 'Firm',
    'A': 'AOP / BOI',
    'T': 'Trust',
    'B': 'BOI',
    'L': 'Local Authority',
    'J': 'AJP',
    'G': 'Government',
}


def extract_pan_number(ocr_text: str) -> Optional[str]:
    """Extract PAN number from OCR text."""
    pan_pattern = re.compile(r'\b([A-Z]{5}[0-9]{4}[A-Z])\b')
    matches = pan_pattern.findall(ocr_text.upper())
    return matches[0] if matches else None


def validate_pan(ocr_text: str) -> VerificationCheck:
    """Validate PAN format and category code."""
    pan = extract_pan_number(ocr_text)
    if pan is None:
        return VerificationCheck(
            check_name="pan_format",
            passed=False,
            detail="Could not extract a valid PAN number from document",
        )
    if not PAN_PATTERN.match(pan):
        return VerificationCheck(
            check_name="pan_format",
            passed=False,
            detail=f"PAN format invalid: {pan}",
        )
    category_code = pan[3]
    category_name = PAN_CATEGORY_CODES.get(category_code, f"Unknown category: {category_code}")
    return VerificationCheck(
        check_name="pan_format",
        passed=True,
        detail=f"PAN {pan} is valid format. 4th char '{category_code}' = {category_name}",
    )


# ===== PASSPORT MRZ VALIDATION =====

MRZ_WEIGHTS = [7, 3, 1]
MRZ_CHARS = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ<'
MRZ_VALUES = {c: i for i, c in enumerate(MRZ_CHARS)}


def mrz_check_digit(field: str) -> int:
    """Compute MRZ check digit per ICAO 9303."""
    total = 0
    for i, c in enumerate(field.upper()):
        val = MRZ_VALUES.get(c, 0)
        total += val * MRZ_WEIGHTS[i % 3]
    return total % 10


def extract_mrz_lines(ocr_text: str) -> Optional[Tuple[str, str]]:
    """Extract MRZ lines (TD3 format: 44 chars each) from OCR text."""
    lines = [line.strip() for line in ocr_text.split('\n')]
    mrz_lines = []
    for line in lines:
        # MRZ lines are 44 chars and only contain A-Z, 0-9, <
        clean = re.sub(r'[^A-Z0-9<]', '', line.upper())
        if len(clean) == 44:
            mrz_lines.append(clean)
    if len(mrz_lines) >= 2:
        return mrz_lines[0], mrz_lines[1]
    return None


def validate_passport_mrz(ocr_text: str) -> VerificationCheck:
    """Validate passport MRZ check digits."""
    mrz = extract_mrz_lines(ocr_text)
    if mrz is None:
        return VerificationCheck(
            check_name="passport_mrz",
            passed=False,
            detail="Could not extract MRZ lines from passport document",
        )
    line1, line2 = mrz

    # Validate passport number (chars 0-8 of line2, check at pos 9)
    passport_num = line2[0:9]
    expected_check = int(line2[9])
    computed_check = mrz_check_digit(passport_num)
    if computed_check != expected_check:
        return VerificationCheck(
            check_name="passport_mrz",
            passed=False,
            detail=f"Passport number MRZ check digit mismatch (expected {expected_check}, got {computed_check})",
        )

    # Validate DOB (chars 13-18, check at 19)
    dob = line2[13:19]
    dob_check = int(line2[19])
    if mrz_check_digit(dob) != dob_check:
        return VerificationCheck(
            check_name="passport_mrz",
            passed=False,
            detail="Passport DOB MRZ check digit mismatch",
        )

    return VerificationCheck(
        check_name="passport_mrz",
        passed=True,
        detail="Passport MRZ check digits validated successfully",
    )

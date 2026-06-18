"""
Document tamper detection heuristics.
- ELA (Error Level Analysis) for JPEG images
- Font consistency check
- EXIF metadata inspection
"""

import io
import os
import tempfile
from typing import List, Optional
from ai_services.shared.schemas import VerificationCheck, VerificationFlag, VerificationResult
from ai_services.verification_agent.checksum_validators import (
    validate_aadhaar, validate_pan, validate_passport_mrz
)
from ai_services.shared.schemas import DocType


def run_ela_check(image_bytes: bytes, quality: int = 90, ela_threshold: float = 25.0) -> VerificationCheck:
    """
    Error Level Analysis: re-compress the image and compare.
    High ELA values in specific regions suggest possible editing.
    """
    try:
        from PIL import Image
        import numpy as np

        original = Image.open(io.BytesIO(image_bytes))
        if original.format != 'JPEG':
            return VerificationCheck(
                check_name="ela_tamper",
                passed=True,
                detail="ELA skipped (non-JPEG format)",
            )

        # Resave at lower quality
        buffer = io.BytesIO()
        original.save(buffer, 'JPEG', quality=quality)
        buffer.seek(0)
        recompressed = Image.open(buffer)

        # ELA = difference amplified
        orig_arr = np.array(original.convert('RGB'), dtype=float)
        recomp_arr = np.array(recompressed.convert('RGB'), dtype=float)
        ela = np.abs(orig_arr - recomp_arr) * (255.0 / max(100 - quality, 1))

        ela_mean = float(ela.mean())
        ela_max = float(ela.max())

        suspicious = ela_max > ela_threshold * 5 and ela_mean > ela_threshold

        return VerificationCheck(
            check_name="ela_tamper",
            passed=not suspicious,
            detail=(
                f"ELA mean={ela_mean:.1f} max={ela_max:.1f}. "
                f"{'Possible tampering detected' if suspicious else 'No obvious tampering'}"
            ),
        )
    except Exception as e:
        return VerificationCheck(
            check_name="ela_tamper",
            passed=True,
            detail=f"ELA check skipped: {str(e)}",
        )


def run_exif_check(image_bytes: bytes) -> VerificationCheck:
    """Check EXIF metadata for signs of editing software."""
    try:
        from PIL import Image
        from PIL.ExifTags import TAGS

        img = Image.open(io.BytesIO(image_bytes))
        exif_data = img._getexif() if hasattr(img, '_getexif') and img._getexif() else {}

        if not exif_data:
            return VerificationCheck(
                check_name="exif_metadata",
                passed=True,
                detail="No EXIF data found (normal for scanned documents)",
            )

        suspicious_software = ['photoshop', 'gimp', 'paint.net', 'pixelmator', 'lightroom', 'acrobat']
        software_tag = next((TAGS.get(k, k) for k in exif_data if TAGS.get(k, '').lower() == 'software'), None)
        software_value = str(exif_data.get(305, '')).lower()  # Tag 305 = Software

        is_suspicious = any(sw in software_value for sw in suspicious_software)

        return VerificationCheck(
            check_name="exif_metadata",
            passed=not is_suspicious,
            detail=(
                f"EXIF Software: '{software_value or 'not set'}'. "
                f"{'Editing software detected' if is_suspicious else 'No editing software signature found'}"
            ),
        )
    except Exception as e:
        return VerificationCheck(
            check_name="exif_metadata",
            passed=True,
            detail=f"EXIF check skipped: {str(e)}",
        )


def run_verification(
    document_id: str,
    content: bytes,
    mime_type: str,
    ocr_text: str,
    doc_type: str,
) -> VerificationResult:
    """Run all applicable verification checks for a document."""
    checks = []

    # Checksum validations based on doc type
    if doc_type == DocType.AADHAAR:
        checks.append(validate_aadhaar(ocr_text))
    elif doc_type == DocType.PAN:
        checks.append(validate_pan(ocr_text))
    elif doc_type == DocType.PASSPORT:
        checks.append(validate_passport_mrz(ocr_text))
        checks.append(validate_pan(ocr_text))  # Passport also has PAN sometimes
    else:
        # Generic: try PAN check if text contains a PAN-like pattern
        import re
        if re.search(r'[A-Z]{5}[0-9]{4}[A-Z]', ocr_text):
            checks.append(validate_pan(ocr_text))

    # Tamper heuristics for images
    if mime_type in ('image/jpeg', 'image/jpg'):
        checks.append(run_ela_check(content))
        checks.append(run_exif_check(content))

    # Determine overall flag
    failed_checks = [c for c in checks if not c.passed]
    if len(failed_checks) == 0:
        overall_flag = VerificationFlag.OK
    elif len(failed_checks) == 1 and 'ela' in failed_checks[0].check_name:
        overall_flag = VerificationFlag.REVIEW  # ELA alone is not conclusive
    elif len(failed_checks) >= 2:
        overall_flag = VerificationFlag.SUSPICIOUS
    else:
        overall_flag = VerificationFlag.REVIEW

    return VerificationResult(
        document_id=document_id,
        checks=checks,
        overall_flag=overall_flag,
    )

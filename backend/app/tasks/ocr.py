"""OCR extraction Celery task.

Pipeline:
  1. Load encrypted document from MinIO
  2. Decrypt using document's DEK
  3. Run PaddleOCR (primary) or Tesseract (fallback)
  4. Send raw OCR text to Ollama LLM for structured field extraction
  5. Write DocumentExtraction record
  6. Upsert ProfileField records (with conflict detection)
"""

import hashlib
import io
import json
import logging
from datetime import datetime, timezone
from typing import Optional

from app.celery_app import celery_app
from app.core.config import settings

logger = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    name="app.tasks.ocr.extract_document_fields",
    max_retries=3,
    default_retry_delay=30,
    queue="ocr",
)
def extract_document_fields(self, document_id: str) -> dict:
    """
    OCR + LLM extraction pipeline for a single document.

    Args:
        document_id: UUID of the Document to process

    Returns:
        dict with extracted fields and confidence scores
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    # Use sync engine for Celery workers
    engine = create_engine(settings.DATABASE_SYNC_URL)
    Session = sessionmaker(bind=engine)

    try:
        with Session() as db:
            # ── 1. Load document record ──────────────────────────────────
            from app.models.document import Document, DocumentExtraction
            doc = db.query(Document).filter(Document.id == document_id).first()
            if not doc:
                logger.error(f"Document {document_id} not found")
                return {"error": "document_not_found"}

            # ── 2. Fetch encrypted content from MinIO ───────────────────
            import boto3
            s3 = boto3.client(
                "s3",
                endpoint_url=f"{'https' if settings.MINIO_USE_SSL else 'http'}://{settings.MINIO_ENDPOINT}",
                aws_access_key_id=settings.MINIO_ACCESS_KEY,
                aws_secret_access_key=settings.MINIO_SECRET_KEY,
            )
            response = s3.get_object(Bucket=settings.MINIO_BUCKET, Key=doc.storage_key)
            encrypted_content = response["Body"].read()

            # ── 3. Decrypt ───────────────────────────────────────────────
            from app.core.encryption import unwrap_dek, decrypt_document_content
            dek = unwrap_dek(doc.encryption_key_id)
            raw_content = decrypt_document_content(encrypted_content, dek)

            # ── 4. OCR ───────────────────────────────────────────────────
            ocr_text, ocr_confidence, language = _run_ocr(raw_content, doc.mime_type)

            # ── 5. LLM structured extraction ─────────────────────────────
            structured_fields = _extract_fields_with_llm(ocr_text, doc.doc_type)

            # ── 6. Store extraction record ────────────────────────────────
            extraction = DocumentExtraction(
                document_id=doc.id,
                raw_blocks={"raw_text": ocr_text},
                structured_fields=structured_fields,
                ocr_confidence=ocr_confidence,
                language_detected=language,
                model_used=f"paddleocr+{settings.OLLAMA_PRIMARY_MODEL}",
            )
            db.add(extraction)

            # ── 7. Upsert ProfileField records ────────────────────────────
            _upsert_profile_fields(db, doc, structured_fields, dek)

            db.commit()
            logger.info(f"Extraction complete for document {document_id}: {len(structured_fields)} fields")
            return {"document_id": document_id, "fields_extracted": len(structured_fields)}

    except Exception as exc:
        logger.exception(f"OCR task failed for document {document_id}: {exc}")
        raise self.retry(exc=exc)


def _run_ocr(content: bytes, mime_type: str) -> tuple[str, float, str]:
    """Run OCR on document content. Returns (text, confidence, language)."""
    if mime_type == "application/pdf":
        content = _pdf_to_image_bytes(content)

    if settings.OCR_ENGINE == "paddleocr":
        try:
            return _paddleocr(content)
        except Exception as e:
            logger.warning(f"PaddleOCR failed, falling back to Tesseract: {e}")

    return _tesseract(content)


def _pdf_to_image_bytes(pdf_content: bytes) -> bytes:
    """Convert first page of PDF to PNG bytes."""
    import fitz  # PyMuPDF
    doc = fitz.open(stream=pdf_content, filetype="pdf")
    page = doc[0]
    mat = fitz.Matrix(2.0, 2.0)  # 2x zoom for better OCR
    pix = page.get_pixmap(matrix=mat)
    return pix.tobytes("png")


def _paddleocr(image_bytes: bytes) -> tuple[str, float, str]:
    """Run PaddleOCR on image bytes."""
    from paddleocr import PaddleOCR
    import numpy as np
    from PIL import Image

    ocr = PaddleOCR(use_angle_cls=True, lang="en", show_log=False)
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    img_array = np.array(img)

    result = ocr.ocr(img_array, cls=True)
    if not result or not result[0]:
        return "", 0.0, "unknown"

    lines = []
    confidences = []
    for line in result[0]:
        text = line[1][0]
        conf = line[1][1]
        lines.append(text)
        confidences.append(conf)

    full_text = " ".join(lines)
    avg_conf = sum(confidences) / len(confidences) if confidences else 0.0
    return full_text, avg_conf, "en"


def _tesseract(image_bytes: bytes) -> tuple[str, float, str]:
    """Run Tesseract OCR as fallback."""
    import pytesseract
    from PIL import Image

    img = Image.open(io.BytesIO(image_bytes))
    data = pytesseract.image_to_data(img, lang=settings.OCR_LANG, output_type=pytesseract.Output.DICT)

    words = [w for w, c in zip(data["text"], data["conf"]) if int(c) > 40 and w.strip()]
    confs = [int(c) for c in data["conf"] if int(c) > 40]

    full_text = " ".join(words)
    avg_conf = (sum(confs) / len(confs) / 100.0) if confs else 0.0
    return full_text, avg_conf, "en"


def _extract_fields_with_llm(ocr_text: str, doc_type: str) -> dict:
    """Use Ollama LLM to extract structured fields from OCR text."""
    import httpx

    prompt = f"""You are an Indian government document parser. Extract structured fields from the following OCR text of a {doc_type} document.

Return a JSON object with field names as keys. Common fields: name, dob, aadhaar_number, pan_number, address, gender, father_name, passport_number, driving_license_number, voter_id, issue_date, expiry_date.

Only include fields that are clearly present in the text. Use null for unclear values.

OCR Text:
{ocr_text[:3000]}

Respond with ONLY valid JSON, no explanation:"""

    try:
        response = httpx.post(
            f"{settings.OLLAMA_HOST}/api/generate",
            json={
                "model": settings.OLLAMA_PRIMARY_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.1},
            },
            timeout=settings.OLLAMA_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        raw = response.json().get("response", "{}")
        # Strip markdown code fences if present
        raw = raw.strip().strip("```json").strip("```").strip()
        return json.loads(raw)
    except Exception as e:
        logger.warning(f"LLM extraction failed: {e}")
        return {}


def _upsert_profile_fields(db, doc, structured_fields: dict, dek: bytes) -> None:
    """Upsert extracted fields into ProfileField, creating conflicts if needed."""
    from app.models.profile_field import ProfileField, ProfileFieldConflict
    from app.core.encryption import encrypt_field

    for field_key, raw_value in structured_fields.items():
        if not raw_value:
            continue
        value_str = str(raw_value).strip()
        if not value_str:
            continue

        encrypted_value = encrypt_field(value_str, dek, field_key)

        existing = (
            db.query(ProfileField)
            .filter(
                ProfileField.profile_id == doc.profile_id,
                ProfileField.field_key == field_key,
            )
            .first()
        )

        if existing:
            # Create conflict record for human resolution
            conflict = ProfileFieldConflict(
                profile_id=doc.profile_id,
                field_key=field_key,
                existing_value_encrypted=existing.field_value_encrypted,
                new_value_encrypted=encrypted_value,
                existing_source_doc_id=existing.source_document_id,
                new_source_doc_id=doc.id,
            )
            db.add(conflict)
        else:
            pf = ProfileField(
                profile_id=doc.profile_id,
                field_key=field_key,
                field_value_encrypted=encrypted_value,
                source_document_id=doc.id,
                confidence=0.85,
            )
            db.add(pf)

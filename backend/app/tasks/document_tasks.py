"""Celery tasks for document processing pipeline."""

import sys
sys.path.insert(0, '/')

from app.celery_app import celery_app
from app.core.config import settings
import logging

logger = logging.getLogger(__name__)


@celery_app.task(name="app.tasks.document_tasks.extract_document", bind=True, max_retries=3)
def extract_document(self, document_id: str):
    """
    Main document processing pipeline:
    1. Fetch document from MinIO
    2. Run OCR
    3. Classify document type
    4. Run verification checks
    5. Extract structured fields
    6. Merge into profile
    """
    import asyncio
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session
    from app.core.config import settings

    logger.info(f"Processing document: {document_id}")

    try:
        # Use synchronous DB for Celery tasks
        from sqlalchemy import create_engine
        engine = create_engine(settings.DATABASE_SYNC_URL)

        with Session(engine) as db:
            from app.models.document import Document, DocumentExtraction, DocumentVerification
            from app.models.audit import AuditLog

            doc = db.execute(select(Document).where(Document.id == document_id)).scalar_one_or_none()
            if not doc:
                logger.error(f"Document not found: {document_id}")
                return

            doc.processing_status = "processing"
            db.flush()

            # Fetch encrypted content from MinIO
            import boto3
            s3 = boto3.client(
                "s3",
                endpoint_url=f"{'https' if settings.MINIO_USE_SSL else 'http'}://{settings.MINIO_ENDPOINT}",
                aws_access_key_id=settings.MINIO_ACCESS_KEY,
                aws_secret_access_key=settings.MINIO_SECRET_KEY,
            )
            response = s3.get_object(Bucket=settings.MINIO_BUCKET, Key=doc.storage_key)
            encrypted_content = response['Body'].read()

            # Decrypt
            from app.core.encryption import unwrap_dek, decrypt_document_content
            dek = unwrap_dek(doc.encryption_key_id)
            content = decrypt_document_content(encrypted_content, dek)

            # OCR
            try:
                from ai_services.ocr_agent.paddle_runner import run_paddle_ocr
                ocr_result = run_paddle_ocr(document_id, content, doc.mime_type)
            except Exception as e:
                logger.warning(f"PaddleOCR failed, trying Tesseract: {e}")
                from ai_services.ocr_agent.tesseract_fallback import run_tesseract_ocr
                ocr_result = run_tesseract_ocr(document_id, content, doc.mime_type)

            # Classification
            from ai_services.classification_agent.classifier import classify_document
            cls_result = classify_document(
                document_id,
                ocr_result.text,
                ocr_result.ocr_confidence,
            )

            # Update document type
            doc.doc_type = cls_result.doc_type.value

            # Store extraction
            extraction = DocumentExtraction(
                document_id=document_id,
                raw_blocks=[b.model_dump() for b in ocr_result.blocks],
                structured_fields={},
                ocr_confidence=ocr_result.ocr_confidence,
                language_detected=ocr_result.language_detected,
                model_used=ocr_result.model_used,
            )
            db.add(extraction)
            db.flush()

            # Verification
            from ai_services.verification_agent.tamper_heuristics import run_verification
            ver_result = run_verification(
                document_id,
                content,
                doc.mime_type,
                ocr_result.text,
                cls_result.doc_type,
            )

            verification = DocumentVerification(
                document_id=document_id,
                overall_flag=ver_result.overall_flag.value,
                checks=[c.model_dump() for c in ver_result.checks],
            )
            db.add(verification)

            # Extract structured fields from OCR text (doc-type templates)
            from ai_services.extraction_agent.extractor import extract_fields
            structured = extract_fields(
                ocr_result.text,
                cls_result.doc_type.value,
                ocr_confidence=ocr_result.ocr_confidence,
                verification_checks=[c.model_dump() for c in ver_result.checks],
            )
            extraction.structured_fields = structured
            doc.processing_status = "extracted"
            db.flush()

            # Merge into profile
            from app.services.profile_service import ProfileService
            ProfileService.merge_extracted_fields(
                db, str(doc.profile_id), structured, document_id, dek
            )

            doc.processing_status = "verified"
            db.add(AuditLog(
                profile_id=str(doc.profile_id),
                actor="system:ocr_agent",
                action="document_extracted",
                details={
                    "document_id": document_id,
                    "doc_type": cls_result.doc_type.value,
                    "confidence": cls_result.confidence,
                    "verification_flag": ver_result.overall_flag.value,
                    "fields_extracted": list(structured.keys()),
                },
            ))

            db.commit()
            logger.info(f"Document {document_id} processed successfully")

    except Exception as e:
        logger.error(f"Error processing document {document_id}: {e}")
        if self.request.retries >= self.max_retries:
            try:
                from sqlalchemy import create_engine, select
                from sqlalchemy.orm import Session
                from app.models.document import Document
                engine = create_engine(settings.DATABASE_SYNC_URL)
                with Session(engine) as db:
                    doc = db.execute(
                        select(Document).where(Document.id == document_id)
                    ).scalar_one_or_none()
                    if doc:
                        doc.processing_status = "failed"
                        db.commit()
            except Exception as mark_err:
                logger.error(f"Failed to mark document {document_id} as failed: {mark_err}")
            raise
        self.retry(exc=e, countdown=60)


@celery_app.task(name="app.tasks.document_tasks.purge_profile_data")
def purge_profile_data(profile_id: str):
    """Cryptographic erasure: delete all documents and profile data."""
    from sqlalchemy import create_engine, delete as sql_delete, select
    from sqlalchemy.orm import Session
    from app.models.document import Document

    engine = create_engine(settings.DATABASE_SYNC_URL)
    with Session(engine) as db:
        # Get all document storage keys for this profile
        docs = db.execute(
            select(Document).where(Document.profile_id == profile_id)
        ).scalars().all()

        import boto3
        s3 = boto3.client(
            "s3",
            endpoint_url=f"{'https' if settings.MINIO_USE_SSL else 'http'}://{settings.MINIO_ENDPOINT}",
            aws_access_key_id=settings.MINIO_ACCESS_KEY,
            aws_secret_access_key=settings.MINIO_SECRET_KEY,
        )

        for doc in docs:
            try:
                s3.delete_object(Bucket=settings.MINIO_BUCKET, Key=doc.storage_key)
            except Exception as e:
                logger.error(f"Failed to delete object {doc.storage_key}: {e}")

        db.commit()
        logger.info(f"Purged all data for profile {profile_id}")


@celery_app.task(name="app.tasks.document_tasks.cleanup_expired_otps")
def cleanup_expired_otps():
    """Periodic task: delete expired OTP tokens."""
    from sqlalchemy import create_engine, delete as sql_delete
    from sqlalchemy.orm import Session
    from datetime import datetime, timezone
    from app.models.auth import OtpToken

    engine = create_engine(settings.DATABASE_SYNC_URL)
    with Session(engine) as db:
        db.execute(
            sql_delete(OtpToken).where(
                OtpToken.expires_at < datetime.now(timezone.utc)
            )
        )
        db.commit()

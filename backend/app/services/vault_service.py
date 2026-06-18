"""Document Vault Service — handles uploads, encryption, deduplication."""

import hashlib
import io
from typing import Optional, Tuple
from uuid import UUID
import boto3
from botocore.exceptions import ClientError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.encryption import generate_dek, wrap_dek, encrypt_document_content
from app.models.document import Document
from app.tasks.document_tasks import extract_document


class VaultService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.s3 = boto3.client(
            "s3",
            endpoint_url=f"{'https' if settings.MINIO_USE_SSL else 'http'}://{settings.MINIO_ENDPOINT}",
            aws_access_key_id=settings.MINIO_ACCESS_KEY,
            aws_secret_access_key=settings.MINIO_SECRET_KEY,
        )

    async def upload_document(
        self,
        profile_id: str,
        content: bytes,
        mime_type: str,
        original_filename: Optional[str] = None,
        doc_type_hint: Optional[str] = None,
    ) -> Tuple[UUID, str]:
        """
        Upload a document:
        1. Compute content hash (SHA-256)
        2. Check for duplicate (same hash, same profile) — dedup
        3. Generate DEK, encrypt content, stream to MinIO
        4. Insert documents row
        5. Enqueue extraction Celery task
        """
        content_hash = hashlib.sha256(content).hexdigest()

        # Check for existing identical document
        existing_result = await self.db.execute(
            select(Document).where(
                Document.profile_id == profile_id,
                Document.content_hash == content_hash,
                Document.is_current == True,
            )
        )
        existing = existing_result.scalar_one_or_none()
        if existing:
            # Exact duplicate — return existing document ID
            return existing.id, "duplicate_existing"

        # Generate per-document DEK
        dek = generate_dek()
        wrapped_dek = wrap_dek(dek)
        encryption_key_id = f"dek:{hashlib.sha256(wrapped_dek.encode()).hexdigest()[:16]}"

        # Encrypt content
        encrypted_content = encrypt_document_content(content, dek)

        # Storage key: profile_id/doc_type/hash.ext
        ext = mime_type.split('/')[-1].replace('jpeg', 'jpg')
        storage_key = f"{profile_id}/{doc_type_hint or 'unknown'}/{content_hash[:16]}.{ext}.enc"

        # Upload to MinIO
        try:
            self.s3.put_object(
                Bucket=settings.MINIO_BUCKET,
                Key=storage_key,
                Body=io.BytesIO(encrypted_content),
                ContentType="application/octet-stream",
                Metadata={
                    "profile_id": profile_id,
                    "content_hash": content_hash,
                    "encryption_key_id": encryption_key_id,
                },
            )
        except Exception as e:
            raise RuntimeError(f"Failed to upload to object storage: {e}")

        # Insert document record
        document = Document(
            profile_id=profile_id,
            doc_type=doc_type_hint or "UNKNOWN",
            storage_key=storage_key,
            content_hash=content_hash,
            encryption_key_id=wrapped_dek,  # Store the wrapped DEK
            mime_type=mime_type,
            size_bytes=len(content),
            is_current=True,
            original_filename=original_filename,
        )
        self.db.add(document)
        await self.db.flush()

        # Enqueue async extraction pipeline
        extract_document.delay(str(document.id))

        return document.id, "processing"

    def get_document_content(self, storage_key: str, wrapped_dek: str) -> bytes:
        """Retrieve and decrypt a document from MinIO."""
        from app.core.encryption import unwrap_dek, decrypt_document_content

        response = self.s3.get_object(Bucket=settings.MINIO_BUCKET, Key=storage_key)
        encrypted_content = response['Body'].read()

        dek = unwrap_dek(wrapped_dek)
        return decrypt_document_content(encrypted_content, dek)

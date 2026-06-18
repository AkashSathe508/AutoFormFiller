"""Document vault endpoints."""

import io
import hashlib
from typing import Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user, set_rls_context
from app.core.config import settings
from app.db.session import get_db
from app.models.user import Profile
from app.models.document import Document, DocumentExtraction, DocumentVerification
from app.models.audit import ConsentLog, AuditLog
from app.services.vault_service import VaultService

router = APIRouter()


@router.post("", status_code=202)
async def upload_document(
    profile_id: str = Form(...),
    doc_type_hint: Optional[str] = Form(None),
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Upload a document to the vault. Returns 202 (async processing)."""
    await set_rls_context(db, user_id=current_user["user_id"], profile_id=profile_id)

    # Verify profile ownership
    profile_result = await db.execute(
        select(Profile).where(
            Profile.id == profile_id,
            Profile.user_id == current_user["user_id"],
            Profile.is_active == True,
        )
    )
    if not profile_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Profile not found")

    # Validate mime type
    if file.content_type not in settings.ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type: {file.content_type}. Allowed: {settings.ALLOWED_MIME_TYPES}",
        )

    # Read and validate file size
    content = await file.read()
    if len(content) > settings.max_upload_size_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Maximum size: {settings.MAX_UPLOAD_SIZE_MB}MB",
        )

    # Log consent for document upload
    db.add(ConsentLog(
        profile_id=profile_id,
        action="document_upload",
        scope=f"file:{file.filename}:type:{doc_type_hint or 'auto'}",
    ))

    # Process upload via vault service
    vault = VaultService(db)
    document_id, status = await vault.upload_document(
        profile_id=profile_id,
        content=content,
        mime_type=file.content_type,
        original_filename=file.filename,
        doc_type_hint=doc_type_hint,
    )

    db.add(AuditLog(
        profile_id=profile_id,
        actor=current_user["user_id"],
        action="document_uploaded",
        details={"document_id": str(document_id), "mime_type": file.content_type},
    ))

    return {"document_id": str(document_id), "status": status}


@router.get("/{document_id}/status")
async def get_document_status(
    document_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get processing status and extracted fields preview."""
    await set_rls_context(db, user_id=current_user["user_id"], bypass=True)

    doc_result = await db.execute(select(Document).where(Document.id == document_id))
    doc = doc_result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # Get latest extraction
    ext_result = await db.execute(
        select(DocumentExtraction)
        .where(DocumentExtraction.document_id == document_id)
        .order_by(DocumentExtraction.extracted_at.desc())
        .limit(1)
    )
    extraction = ext_result.scalar_one_or_none()

    # Get verification
    ver_result = await db.execute(
        select(DocumentVerification)
        .where(DocumentVerification.document_id == document_id)
        .order_by(DocumentVerification.verified_at.desc())
        .limit(1)
    )
    verification = ver_result.scalar_one_or_none()

    status = "uploaded"
    if extraction:
        status = "extracted"
    if verification:
        status = "verified"

    extracted_fields = []
    if extraction and extraction.structured_fields:
        extracted_fields = list(extraction.structured_fields.keys())

    return {
        "document_id": document_id,
        "doc_type": doc.doc_type,
        "status": status,
        "verification_flag": verification.overall_flag if verification else None,
        "extracted_fields_preview": extracted_fields,
        "uploaded_at": doc.uploaded_at.isoformat(),
    }


@router.get("")
async def list_documents(
    profile_id: str = Query(...),
    doc_type: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List vault documents for a profile (metadata only)."""
    await set_rls_context(db, user_id=current_user["user_id"], profile_id=profile_id)

    query = select(Document).where(
        Document.profile_id == profile_id,
        Document.is_current == True,
    )
    if doc_type:
        query = query.where(Document.doc_type == doc_type.upper())
    query = query.order_by(Document.uploaded_at.desc())

    result = await db.execute(query)
    docs = result.scalars().all()

    return {
        "documents": [
            {
                "document_id": str(d.id),
                "doc_type": d.doc_type,
                "mime_type": d.mime_type,
                "size_bytes": d.size_bytes,
                "version": d.version,
                "uploaded_at": d.uploaded_at.isoformat(),
                "expires_hint_at": d.expires_hint_at.isoformat() if d.expires_hint_at else None,
            }
            for d in docs
        ]
    }

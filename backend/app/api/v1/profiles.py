"""Profile management endpoints."""

from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user, set_rls_context
from app.core.encryption import encrypt_field, decrypt_field, mask_field_value, SENSITIVE_FIELD_KEYS, generate_dek
from app.db.session import get_db
from app.models.user import User, Profile
from app.models.profile_field import ProfileField
from app.models.document import Document
from app.models.form import FormInstance
from app.models.audit import AuditLog, ConsentLog

router = APIRouter()


class CreateProfileRequest(BaseModel):
    display_name: str
    relation_to_account: str = "self"


class ProfileResponse(BaseModel):
    profile_id: str
    display_name: str
    relation_to_account: str


@router.post("", status_code=201)
async def create_profile(
    request: CreateProfileRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new profile (self or family member)."""
    await set_rls_context(db, user_id=current_user["user_id"], bypass=True)

    profile = Profile(
        user_id=current_user["user_id"],
        display_name=request.display_name,
        relation_to_account=request.relation_to_account,
    )
    db.add(profile)
    await db.flush()

    # Consent log
    db.add(ConsentLog(
        profile_id=profile.id,
        action="profile_created",
        scope=str(profile.id),
    ))

    # Audit log
    db.add(AuditLog(
        profile_id=profile.id,
        actor=current_user["user_id"],
        action="profile_created",
        details={"display_name": request.display_name},
    ))

    return {"profile_id": str(profile.id), "display_name": profile.display_name}


@router.get("")
async def list_profiles(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all profiles for the current user."""
    await set_rls_context(db, user_id=current_user["user_id"])
    result = await db.execute(
        select(Profile)
        .where(Profile.user_id == current_user["user_id"], Profile.is_active == True)
        .order_by(Profile.created_at)
    )
    profiles = result.scalars().all()
    return {
        "profiles": [
            {
                "profile_id": str(p.id),
                "display_name": p.display_name,
                "relation_to_account": p.relation_to_account,
            }
            for p in profiles
        ]
    }


@router.get("/{profile_id}/fields")
async def get_profile_fields(
    profile_id: str,
    reveal: bool = Query(False),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get all profile fields with provenance. Sensitive fields masked by default."""
    await set_rls_context(db, user_id=current_user["user_id"], profile_id=profile_id)

    # Verify ownership
    profile_result = await db.execute(
        select(Profile).where(Profile.id == profile_id, Profile.user_id == current_user["user_id"])
    )
    profile = profile_result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")

    fields_result = await db.execute(
        select(ProfileField).where(ProfileField.profile_id == profile_id)
    )
    profile_fields = fields_result.scalars().all()

    # We need profile DEK to decrypt. For MVP: derive from profile ID.
    # Production: stored wrapped DEK per profile.
    from app.core.encryption import unwrap_dek
    # DEK placeholder — in production each profile has its own wrapped DEK stored in DB
    dek = generate_dek()  # This would be loaded from stored wrapped DEK in production

    response_fields = []
    for field in profile_fields:
        try:
            decrypted = decrypt_field(field.field_value_encrypted, dek, field.field_key)
        except Exception:
            decrypted = "[decryption error]"

        if not reveal and field.field_key in SENSITIVE_FIELD_KEYS:
            display_value = mask_field_value(field.field_key, decrypted)
        else:
            display_value = decrypted

        response_fields.append({
            "field_key": field.field_key,
            "value": display_value,
            "confidence": field.confidence,
            "source_document_id": str(field.source_document_id) if field.source_document_id else None,
            "user_confirmed": field.user_confirmed,
            "updated_at": field.updated_at.isoformat() if field.updated_at else None,
        })

    return {"profile_id": profile_id, "fields": response_fields}


@router.delete("/{profile_id}")
async def delete_profile(
    profile_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    DPDP Right to Erasure: destroys profile's DEK, schedules data purge.
    Cryptographic erasure — encrypted data becomes permanently unreadable.
    """
    await set_rls_context(db, user_id=current_user["user_id"], profile_id=profile_id)

    profile_result = await db.execute(
        select(Profile).where(Profile.id == profile_id, Profile.user_id == current_user["user_id"])
    )
    profile = profile_result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")

    # Mark as inactive (soft delete — hard delete scheduled async)
    profile.is_active = False

    # Audit log the erasure request
    db.add(AuditLog(
        profile_id=None,  # Can't reference deleted profile
        actor=current_user["user_id"],
        action="profile_erasure_requested",
        details={"profile_id": profile_id, "display_name": profile.display_name},
    ))

    # Queue the actual async purge task
    from app.tasks.document_tasks import purge_profile_data
    purge_profile_data.delay(profile_id)

    return {
        "message": "Erasure initiated. Documents will be unrecoverable within 24 hours.",
        "profile_id": profile_id,
    }


@router.get("/{profile_id}/export")
async def export_profile(
    profile_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Data portability export (DPDP / GDPR Art. 20)."""
    await set_rls_context(db, user_id=current_user["user_id"], profile_id=profile_id)

    profile_result = await db.execute(
        select(Profile).where(Profile.id == profile_id, Profile.user_id == current_user["user_id"])
    )
    profile = profile_result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")

    docs_result = await db.execute(
        select(Document).where(Document.profile_id == profile_id, Document.is_current == True)
    )
    documents = docs_result.scalars().all()

    instances_result = await db.execute(
        select(FormInstance).where(FormInstance.profile_id == profile_id)
    )
    instances = instances_result.scalars().all()

    return {
        "profile": {
            "id": str(profile.id),
            "display_name": profile.display_name,
            "relation_to_account": profile.relation_to_account,
        },
        "documents_metadata": [
            {
                "id": str(d.id),
                "doc_type": d.doc_type,
                "version": d.version,
                "uploaded_at": d.uploaded_at.isoformat(),
            }
            for d in documents
        ],
        "form_instances": [
            {
                "id": str(fi.id),
                "status": fi.status,
                "created_at": fi.created_at.isoformat(),
            }
            for fi in instances
        ],
        "exported_at": __import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat(),
    }

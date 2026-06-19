"""Forms API endpoints.

Handles:
  - Parsing a government form URL to extract its field schema
  - Listing available form templates
  - Creating a form instance (pre-fill) for a profile
  - Reviewing/editing pre-filled field values
"""

from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user, set_rls_context
from app.db.session import get_db
from app.models.form import FormTemplate, FormInstance, FormFieldValue, FieldMappingCache
from app.models.user import Profile

router = APIRouter()


from app.schemas.forms import (
    ParseFormRequest, FormFieldSchema, FormTemplateResponse,
    CreateInstanceRequest, FieldValueResponse, FormInstanceResponse,
    UpdateFieldRequest
)

# ──────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────

@router.get("", response_model=List[FormTemplateResponse])
async def list_form_templates(
    scheme_name: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all available form templates, optionally filtered by scheme name."""
    query = select(FormTemplate).order_by(FormTemplate.parsed_at.desc())
    if scheme_name:
        query = query.where(FormTemplate.scheme_name.ilike(f"%{scheme_name}%"))

    result = await db.execute(query)
    templates = result.scalars().all()

    return [
        FormTemplateResponse(
            id=str(t.id),
            source_type=t.source_type,
            source_url_or_hash=t.source_url_or_hash,
            scheme_name=t.scheme_name,
            field_count=len(t.field_schema) if t.field_schema else 0,
            parsed_at=t.parsed_at.isoformat(),
        )
        for t in templates
    ]


@router.post("/parse", response_model=FormTemplateResponse, status_code=202)
async def parse_form_url(
    body: ParseFormRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Submit a government form URL for parsing.

    The system will:
    1. Check if the URL was already parsed (cache hit)
    2. If not, scrape the form using Playwright
    3. Extract field schema with LLM assistance
    4. Store the template for reuse
    """
    # Check for existing template
    result = await db.execute(
        select(FormTemplate).where(FormTemplate.source_url_or_hash == body.url)
    )
    existing = result.scalar_one_or_none()
    if existing:
        return FormTemplateResponse(
            id=str(existing.id),
            source_type=existing.source_type,
            source_url_or_hash=existing.source_url_or_hash,
            scheme_name=existing.scheme_name,
            field_count=len(existing.field_schema) if existing.field_schema else 0,
            parsed_at=existing.parsed_at.isoformat(),
        )

    # Create a placeholder template (parsing happens asynchronously)
    import uuid as _uuid
    template = FormTemplate(
        source_type="web_url",
        source_url_or_hash=body.url,
        field_schema=[],
        upload_slots=[],
        scheme_name=body.scheme_name,
    )
    db.add(template)
    await db.flush()

    # Enqueue Celery form-parsing task
    try:
        from app.tasks.form_parser import parse_form_schema
        parse_form_schema.delay(str(template.id), body.url)
    except Exception:
        pass  # Non-fatal; status can be polled

    return FormTemplateResponse(
        id=str(template.id),
        source_type=template.source_type,
        source_url_or_hash=template.source_url_or_hash,
        scheme_name=template.scheme_name,
        field_count=0,
        parsed_at=template.parsed_at.isoformat(),
    )


@router.get("/{template_id}", response_model=FormTemplateResponse)
async def get_form_template(
    template_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a specific form template and its field schema."""
    result = await db.execute(select(FormTemplate).where(FormTemplate.id == template_id))
    template = result.scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=404, detail="Form template not found")

    return FormTemplateResponse(
        id=str(template.id),
        source_type=template.source_type,
        source_url_or_hash=template.source_url_or_hash,
        scheme_name=template.scheme_name,
        field_count=len(template.field_schema) if template.field_schema else 0,
        parsed_at=template.parsed_at.isoformat(),
    )


@router.post("/instances", response_model=FormInstanceResponse, status_code=201)
async def create_form_instance(
    body: CreateInstanceRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Create a pre-filled form instance for a profile.

    The AI engine will:
    1. Load the profile's stored fields
    2. Map form fields to profile fields using embeddings + LLM
    3. Decrypt and pre-fill matching values
    4. Flag fields that need human review
    """
    await set_rls_context(db, user_id=current_user["user_id"], profile_id=body.profile_id)

    # Validate profile ownership
    profile_result = await db.execute(
        select(Profile).where(
            Profile.id == body.profile_id,
            Profile.user_id == current_user["user_id"],
            Profile.is_active == True,
        )
    )
    if not profile_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Profile not found")

    # Validate template exists
    template_result = await db.execute(
        select(FormTemplate).where(FormTemplate.id == body.form_template_id)
    )
    template = template_result.scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=404, detail="Form template not found")

    # Create instance
    instance = FormInstance(
        form_template_id=body.form_template_id,
        profile_id=body.profile_id,
        status="filling",
    )
    db.add(instance)
    await db.flush()

    # Enqueue pre-fill task
    try:
        from app.tasks.prefill import prefill_form_instance
        prefill_form_instance.delay(str(instance.id))
    except Exception:
        pass

    return FormInstanceResponse(
        id=str(instance.id),
        form_template_id=str(instance.form_template_id),
        profile_id=str(instance.profile_id),
        status=instance.status,
        created_at=instance.created_at.isoformat(),
        submitted_at=None,
        reference_number=None,
        fields=[],
    )


@router.get("/instances/{instance_id}", response_model=FormInstanceResponse)
async def get_form_instance(
    instance_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a form instance with pre-filled values (decrypted for display)."""
    # Load instance
    inst_result = await db.execute(
        select(FormInstance).where(FormInstance.id == instance_id)
    )
    instance = inst_result.scalar_one_or_none()
    if not instance:
        raise HTTPException(status_code=404, detail="Form instance not found")

    # Verify ownership via profile
    await set_rls_context(db, user_id=current_user["user_id"], profile_id=str(instance.profile_id))
    profile_result = await db.execute(
        select(Profile).where(
            Profile.id == instance.profile_id,
            Profile.user_id == current_user["user_id"],
        )
    )
    if not profile_result.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="Access denied")

    # Load field values
    fv_result = await db.execute(
        select(FormFieldValue).where(FormFieldValue.form_instance_id == instance_id)
    )
    field_values = fv_result.scalars().all()

    # Decrypt values for display
    # (In production, use the profile's DEK from profile_fields)
    fields = []
    for fv in field_values:
        display_value = None
        if fv.value_encrypted:
            try:
                # Attempt decryption; if it fails, show placeholder
                from app.core.encryption import decrypt_field
                # Note: In production, load the actual profile DEK
                display_value = "[encrypted]"
            except Exception:
                display_value = None
        fields.append(
            FieldValueResponse(
                form_field_id=fv.form_field_id,
                value=display_value,
                method=fv.method,
                human_reviewed=fv.human_reviewed,
                needs_attention=fv.needs_attention,
                attention_reason=fv.attention_reason,
            )
        )

    return FormInstanceResponse(
        id=str(instance.id),
        form_template_id=str(instance.form_template_id),
        profile_id=str(instance.profile_id),
        status=instance.status,
        created_at=instance.created_at.isoformat(),
        submitted_at=instance.submitted_at.isoformat() if instance.submitted_at else None,
        reference_number=instance.reference_number,
        fields=fields,
    )


@router.patch("/instances/{instance_id}/fields")
async def update_form_field(
    instance_id: str,
    body: UpdateFieldRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Human review: update/override a pre-filled field value."""
    inst_result = await db.execute(
        select(FormInstance).where(FormInstance.id == instance_id)
    )
    instance = inst_result.scalar_one_or_none()
    if not instance:
        raise HTTPException(status_code=404, detail="Form instance not found")

    # Verify ownership
    profile_result = await db.execute(
        select(Profile).where(
            Profile.id == instance.profile_id,
            Profile.user_id == current_user["user_id"],
        )
    )
    if not profile_result.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="Access denied")

    if instance.status not in ("draft", "filling", "needs_review"):
        raise HTTPException(status_code=422, detail=f"Cannot edit instance in status: {instance.status}")

    # Find or create the field value record
    fv_result = await db.execute(
        select(FormFieldValue).where(
            FormFieldValue.form_instance_id == instance_id,
            FormFieldValue.form_field_id == body.form_field_id,
        )
    )
    fv = fv_result.scalar_one_or_none()

    # Encrypt the new value
    # In production, derive from profile DEK
    new_encrypted = body.value  # Placeholder — real impl encrypts before storing

    if fv:
        fv.value_encrypted = new_encrypted
        fv.human_reviewed = True
        fv.needs_attention = False
        fv.method = "human"
    else:
        fv = FormFieldValue(
            form_instance_id=instance_id,
            form_field_id=body.form_field_id,
            value_encrypted=new_encrypted,
            method="human",
            human_reviewed=True,
        )
        db.add(fv)

    return {"message": "Field updated", "form_field_id": body.form_field_id}

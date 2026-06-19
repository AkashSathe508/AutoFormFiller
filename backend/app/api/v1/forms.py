"""Forms API endpoints — Phase 2.

Endpoints:
  GET    /forms                                 List all form templates
  GET    /forms/{template_id}                   Get template + full field_schema
  POST   /forms/parse                           Submit a web URL for parsing
  POST   /forms/parse-pdf                       Upload a PDF for parsing
  POST   /forms/instances                       Create a pre-filled form instance
  GET    /forms/instances/{instance_id}         Get instance with decrypted values
  PATCH  /forms/instances/{instance_id}/fields  Human review: override a field
  GET    /forms/instances/{instance_id}/gaps    Gap detection report
  POST   /forms/instances/{instance_id}/approve Human approval gate
"""

import base64
import hashlib
import logging
from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import decrypt_field, encrypt_field, unwrap_dek
from app.core.security import get_current_user, set_rls_context
from app.db.session import get_db
from app.models.form import FieldMappingCache, FormFieldValue, FormInstance, FormTemplate
from app.models.profile_field import ProfileField
from app.models.user import Profile
from app.schemas.forms import (
    ApproveInstanceRequest,
    ApproveInstanceResponse,
    CreateInstanceRequest,
    FieldValueResponse,
    FormInstanceResponse,
    FormTemplateResponse,
    FormFieldSchema,
    GapFieldInfo,
    GapReportResponse,
    ParseFormRequest,
    UpdateFieldRequest,
    UploadSlotSchema,
)

router = APIRouter()
logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _template_to_response(t: FormTemplate, include_fields: bool = False) -> FormTemplateResponse:
    field_schema = t.field_schema or []
    upload_slots = t.upload_slots or []
    return FormTemplateResponse(
        id=str(t.id),
        source_type=t.source_type,
        source_url_or_hash=t.source_url_or_hash,
        scheme_name=t.scheme_name,
        version=t.version,
        field_count=len(field_schema),
        upload_slot_count=len(upload_slots),
        parse_method=None,  # not persisted; only returned at parse-time
        parsed_at=t.parsed_at.isoformat(),
        status="parsing" if not field_schema else "ready",
        fields=[FormFieldSchema(**f) for f in field_schema] if include_fields else None,
        upload_slots=[UploadSlotSchema(**s) for s in upload_slots] if include_fields else None,
    )


async def _load_profile_dek(db: AsyncSession, profile_id: str) -> Optional[bytes]:
    """Return a usable DEK from the profile's most recent verified document."""
    from app.models.document import Document
    result = await db.execute(
        select(Document)
        .where(
            Document.profile_id == profile_id,
            Document.is_current == True,
            Document.encryption_key_id != None,
        )
        .order_by(Document.uploaded_at.desc())
        .limit(1)
    )
    doc = result.scalar_one_or_none()
    if not doc:
        return None
    try:
        return unwrap_dek(doc.encryption_key_id)
    except Exception as e:
        logger.warning("DEK unwrap failed for profile %s: %s", profile_id, e)
        return None


# ──────────────────────────────────────────────────────────────────────────────
# Template endpoints
# ──────────────────────────────────────────────────────────────────────────────

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
    return [_template_to_response(t) for t in templates]


@router.get("/{template_id}", response_model=FormTemplateResponse)
async def get_form_template(
    template_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a specific form template with its complete field schema."""
    result = await db.execute(
        select(FormTemplate).where(FormTemplate.id == template_id)
    )
    template = result.scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=404, detail="Form template not found")
    return _template_to_response(template, include_fields=True)


@router.post("/parse", response_model=FormTemplateResponse, status_code=202)
async def parse_form_url(
    body: ParseFormRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Submit a government form URL for parsing via Playwright.

    Returns immediately (202 Accepted). Poll GET /forms/{id} until
    field_count > 0 to know when parsing is complete.
    """
    # Cache check
    result = await db.execute(
        select(FormTemplate).where(FormTemplate.source_url_or_hash == body.url)
    )
    existing = result.scalar_one_or_none()
    if existing:
        return _template_to_response(existing, include_fields=True)

    template = FormTemplate(
        source_type="web_url",
        source_url_or_hash=body.url,
        field_schema=[],
        upload_slots=[],
        scheme_name=body.scheme_name,
    )
    db.add(template)
    await db.flush()

    try:
        from app.tasks.form_parser import parse_form_schema
        parse_form_schema.delay(str(template.id), body.url)
    except Exception as e:
        logger.warning("Failed to enqueue parse_form_schema: %s", e)

    resp = _template_to_response(template)
    resp.status = "parsing"
    return resp


@router.post("/parse-pdf", response_model=FormTemplateResponse, status_code=202)
async def parse_pdf_form(
    file: UploadFile = File(..., description="PDF form to parse"),
    scheme_name: Optional[str] = Form(None),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Upload a PDF form for field extraction.

    - If the same PDF (by SHA-256 hash) was previously parsed, returns the
      cached template immediately.
    - Otherwise, creates a placeholder template and enqueues a Celery task.
      Poll GET /forms/{id} until field_count > 0.
    """
    if file.content_type not in ("application/pdf", "application/octet-stream"):
        # Allow octet-stream in case browser sends wrong MIME
        if not file.filename.lower().endswith(".pdf"):
            raise HTTPException(
                status_code=415,
                detail="Only PDF files are accepted for PDF form parsing.",
            )

    pdf_bytes = await file.read()
    if len(pdf_bytes) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    # Dedup by SHA-256
    pdf_hash = hashlib.sha256(pdf_bytes).hexdigest()
    result = await db.execute(
        select(FormTemplate).where(FormTemplate.source_url_or_hash == pdf_hash)
    )
    existing = result.scalar_one_or_none()
    if existing:
        return _template_to_response(existing, include_fields=True)

    template = FormTemplate(
        source_type="pdf",
        source_url_or_hash=pdf_hash,
        field_schema=[],
        upload_slots=[],
        scheme_name=scheme_name,
    )
    db.add(template)
    await db.flush()

    try:
        from app.tasks.form_parser import parse_pdf_form as celery_parse_pdf
        pdf_b64 = base64.b64encode(pdf_bytes).decode("utf-8")
        celery_parse_pdf.delay(str(template.id), pdf_b64, file.filename or "form.pdf")
    except Exception as e:
        logger.warning("Failed to enqueue parse_pdf_form: %s", e)

    resp = _template_to_response(template)
    resp.status = "parsing"
    return resp


# ──────────────────────────────────────────────────────────────────────────────
# Instance endpoints
# ──────────────────────────────────────────────────────────────────────────────

@router.post("/instances", response_model=FormInstanceResponse, status_code=201)
async def create_form_instance(
    body: CreateInstanceRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a pre-filled form instance for a profile.

    Immediately enqueues the Celery prefill task. Poll GET /instances/{id}
    to observe status transitions: filling → needs_review | ready.
    """
    await set_rls_context(db, user_id=current_user["user_id"], profile_id=body.profile_id)

    profile_result = await db.execute(
        select(Profile).where(
            Profile.id == body.profile_id,
            Profile.user_id == current_user["user_id"],
            Profile.is_active == True,
        )
    )
    if not profile_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Profile not found")

    template_result = await db.execute(
        select(FormTemplate).where(FormTemplate.id == body.form_template_id)
    )
    template = template_result.scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=404, detail="Form template not found")

    if not template.field_schema:
        raise HTTPException(
            status_code=409,
            detail="Form template is still being parsed. Try again in a few seconds.",
        )

    instance = FormInstance(
        form_template_id=body.form_template_id,
        profile_id=body.profile_id,
        status="filling",
    )
    db.add(instance)
    await db.flush()

    try:
        from app.tasks.prefill import prefill_form_instance
        prefill_form_instance.delay(str(instance.id))
    except Exception as e:
        logger.warning("Failed to enqueue prefill_form_instance: %s", e)

    return FormInstanceResponse(
        id=str(instance.id),
        form_template_id=str(instance.form_template_id),
        profile_id=str(instance.profile_id),
        status=instance.status,
        created_at=instance.created_at.isoformat(),
        fields=[],
        total_fields=len(template.field_schema),
    )


@router.get("/instances/{instance_id}", response_model=FormInstanceResponse)
async def get_form_instance(
    instance_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a form instance with pre-filled, decrypted field values.

    Decrypts all form_field_values using the profile's primary document DEK
    so the review UI receives plain-text values.
    """
    inst_result = await db.execute(
        select(FormInstance).where(FormInstance.id == instance_id)
    )
    instance = inst_result.scalar_one_or_none()
    if not instance:
        raise HTTPException(status_code=404, detail="Form instance not found")

    await set_rls_context(db, user_id=current_user["user_id"], profile_id=str(instance.profile_id))
    profile_result = await db.execute(
        select(Profile).where(
            Profile.id == instance.profile_id,
            Profile.user_id == current_user["user_id"],
        )
    )
    if not profile_result.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="Access denied")

    # Load template for label enrichment
    tmpl_result = await db.execute(
        select(FormTemplate).where(FormTemplate.id == instance.form_template_id)
    )
    template = tmpl_result.scalar_one_or_none()
    field_meta: dict = {}
    if template and template.field_schema:
        for f in template.field_schema:
            field_meta[f["field_id"]] = f

    # Resolve profile DEK for decryption
    profile_dek = await _load_profile_dek(db, str(instance.profile_id))

    # Load field values
    fv_result = await db.execute(
        select(FormFieldValue).where(FormFieldValue.form_instance_id == instance_id)
    )
    field_values = fv_result.scalars().all()

    fields: List[FieldValueResponse] = []
    filled = 0
    attention = 0

    for fv in field_values:
        meta = field_meta.get(fv.form_field_id, {})

        # Decrypt value
        display_value: Optional[str] = None
        if fv.value_encrypted:
            try:
                if profile_dek:
                    display_value = decrypt_field(
                        fv.value_encrypted, profile_dek, fv.form_field_id
                    )
                else:
                    # Dev mode — value stored as plain text
                    display_value = fv.value_encrypted
                filled += 1
            except Exception as e:
                logger.warning("Decrypt error for field %s on instance %s: %s",
                               fv.form_field_id, instance_id, e)
                display_value = None

        if fv.needs_attention:
            attention += 1

        fields.append(
            FieldValueResponse(
                form_field_id=fv.form_field_id,
                label=meta.get("label"),
                field_type=meta.get("field_type"),
                required=meta.get("required", False),
                value=display_value,
                method=fv.method,
                source_field_key=fv.source_field_key,
                confidence=fv.confidence,
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
        total_fields=len(field_values),
        filled_fields=filled,
        attention_fields=attention,
    )


@router.patch("/instances/{instance_id}/fields")
async def update_form_field(
    instance_id: str,
    body: UpdateFieldRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Human review: update/override a pre-filled field value.

    Encrypts the incoming plain-text value with the profile's DEK before
    storing. Marks the field as human_reviewed=True.
    """
    inst_result = await db.execute(
        select(FormInstance).where(FormInstance.id == instance_id)
    )
    instance = inst_result.scalar_one_or_none()
    if not instance:
        raise HTTPException(status_code=404, detail="Form instance not found")

    profile_result = await db.execute(
        select(Profile).where(
            Profile.id == instance.profile_id,
            Profile.user_id == current_user["user_id"],
        )
    )
    if not profile_result.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="Access denied")

    if instance.status in ("approved", "submitted"):
        raise HTTPException(
            status_code=422,
            detail=f"Cannot edit a form instance in '{instance.status}' status.",
        )

    # Encrypt the new value with the profile DEK
    profile_dek = await _load_profile_dek(db, str(instance.profile_id))
    if profile_dek:
        new_encrypted = encrypt_field(body.value, profile_dek, body.form_field_id)
    else:
        # Dev fallback — store plain
        new_encrypted = body.value

    fv_result = await db.execute(
        select(FormFieldValue).where(
            FormFieldValue.form_instance_id == instance_id,
            FormFieldValue.form_field_id == body.form_field_id,
        )
    )
    fv = fv_result.scalar_one_or_none()

    if fv:
        fv.value_encrypted = new_encrypted
        fv.human_reviewed = True
        fv.needs_attention = False
        fv.attention_reason = None
        fv.method = "human"
        fv.confidence = 1.0
    else:
        fv = FormFieldValue(
            form_instance_id=instance_id,
            form_field_id=body.form_field_id,
            value_encrypted=new_encrypted,
            method="human",
            human_reviewed=True,
            confidence=1.0,
        )
        db.add(fv)

    await db.commit()
    return {"message": "Field updated", "form_field_id": body.form_field_id}


# ──────────────────────────────────────────────────────────────────────────────
# Milestone 4 — Gap Detection
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/instances/{instance_id}/gaps", response_model=GapReportResponse)
async def get_gap_report(
    instance_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a gap detection report for a form instance.

    Identifies:
    - Fields with no profile mapping (method='none')
    - Required fields that are unmapped
    - Fields flagged needs_attention=True
    """
    inst_result = await db.execute(
        select(FormInstance).where(FormInstance.id == instance_id)
    )
    instance = inst_result.scalar_one_or_none()
    if not instance:
        raise HTTPException(status_code=404, detail="Form instance not found")

    profile_result = await db.execute(
        select(Profile).where(
            Profile.id == instance.profile_id,
            Profile.user_id == current_user["user_id"],
        )
    )
    if not profile_result.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="Access denied")

    # Load template for label/required info
    tmpl_result = await db.execute(
        select(FormTemplate).where(FormTemplate.id == instance.form_template_id)
    )
    template = tmpl_result.scalar_one_or_none()
    field_meta: dict = {}
    if template and template.field_schema:
        for f in template.field_schema:
            field_meta[f["field_id"]] = f

    # Load field values
    fv_result = await db.execute(
        select(FormFieldValue).where(FormFieldValue.form_instance_id == instance_id)
    )
    field_values = fv_result.scalars().all()

    total = len(field_values)
    filled = 0
    attention = 0
    unmapped = 0
    gaps: List[GapFieldInfo] = []
    has_required_gap = False

    for fv in field_values:
        meta = field_meta.get(fv.form_field_id, {})
        required = meta.get("required", False)

        if fv.value_encrypted:
            filled += 1

        if fv.needs_attention or fv.method == "none" or not fv.value_encrypted:
            if fv.method == "none" or not fv.value_encrypted:
                unmapped += 1
            if fv.needs_attention:
                attention += 1

            if required and not fv.value_encrypted:
                has_required_gap = True

            gaps.append(GapFieldInfo(
                field_id=fv.form_field_id,
                label=meta.get("label", fv.form_field_id),
                required=required,
                reason=fv.attention_reason or "No profile field match found",
                method=fv.method,
            ))

    completion_pct = round((filled / total * 100) if total > 0 else 0.0, 1)

    return GapReportResponse(
        instance_id=instance_id,
        status=instance.status,
        total_fields=total,
        filled_fields=filled,
        attention_fields=attention,
        unmapped_fields=unmapped,
        completion_percentage=completion_pct,
        gaps=gaps,
        can_approve=not has_required_gap,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Milestone 5 — Human Approval Gate
# ──────────────────────────────────────────────────────────────────────────────

@router.post("/instances/{instance_id}/approve", response_model=ApproveInstanceResponse)
async def approve_form_instance(
    instance_id: str,
    body: ApproveInstanceRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Human approval gate — transition instance to 'approved'.

    Rules (hardcoded, not LLM-decided):
    - Instance must be in 'needs_review' or 'ready' status.
    - If any required field is unfilled, approval is blocked unless
      body.override_attention=True (user explicitly acknowledges).
    - Logs consent in consent_log.
    - This is NOT submission — it moves to 'approved'; a separate
      submission flow (Phase 3) handles portal integration.
    """
    inst_result = await db.execute(
        select(FormInstance).where(FormInstance.id == instance_id)
    )
    instance = inst_result.scalar_one_or_none()
    if not instance:
        raise HTTPException(status_code=404, detail="Form instance not found")

    profile_result = await db.execute(
        select(Profile).where(
            Profile.id == instance.profile_id,
            Profile.user_id == current_user["user_id"],
        )
    )
    if not profile_result.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="Access denied")

    if instance.status not in ("needs_review", "ready", "filling"):
        raise HTTPException(
            status_code=422,
            detail=f"Cannot approve instance in '{instance.status}' status.",
        )

    # Load template for required field info
    tmpl_result = await db.execute(
        select(FormTemplate).where(FormTemplate.id == instance.form_template_id)
    )
    template = tmpl_result.scalar_one_or_none()
    required_field_ids = set()
    if template and template.field_schema:
        for f in template.field_schema:
            if f.get("required"):
                required_field_ids.add(f["field_id"])

    # Count remaining attention fields
    fv_result = await db.execute(
        select(FormFieldValue).where(FormFieldValue.form_instance_id == instance_id)
    )
    field_values = fv_result.scalars().all()

    attention_remaining = 0
    required_unfilled = 0
    for fv in field_values:
        if fv.needs_attention and not fv.human_reviewed:
            attention_remaining += 1
        if fv.form_field_id in required_field_ids and not fv.value_encrypted:
            required_unfilled += 1

    if required_unfilled > 0 and not body.override_attention:
        raise HTTPException(
            status_code=422,
            detail=(
                f"{required_unfilled} required field(s) are unfilled. "
                "Fill them or set override_attention=true to acknowledge and proceed."
            ),
        )

    # Transition to approved
    now = datetime.now(timezone.utc)
    instance.status = "approved"

    # Log consent
    from app.models.audit import ConsentLog
    consent = ConsentLog(
        profile_id=str(instance.profile_id),
        action="form_instance_approved",
        scope=f"form_instance:{instance_id}",
    )
    db.add(consent)

    await db.commit()

    return ApproveInstanceResponse(
        instance_id=instance_id,
        status="approved",
        approved_at=now.isoformat(),
        attention_fields_remaining=attention_remaining,
        message=(
            "Form instance approved. All values are locked for submission."
            if attention_remaining == 0
            else f"Approved with {attention_remaining} field(s) still needing attention."
        ),
    )

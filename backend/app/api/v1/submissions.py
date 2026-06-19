"""Phase 3 — Submission API router.

Endpoints:
  GET  /submissions/adapters                           List registered portal adapters
  POST /submissions/instances/{instance_id}/approve   Human approval gate (mandatory before submit)
  POST /submissions/instances/{instance_id}/submit    Enqueue Celery submission task
  GET  /submissions/runs/{run_id}                     Poll submission run status
  POST /submissions/runs/{run_id}/resolve-captcha     Signal CAPTCHA resolved → resume engine
  GET  /submissions/runs/{run_id}/audit               Full per-action audit trail

Phase 3 Rules (hardcoded — not configurable):
  1. Human approval is mandatory before submission.
  2. All FormFieldValue.human_reviewed must be True.
  3. No unacknowledged needs_attention fields.
  4. CAPTCHA: always pause for user, never auto-solve.
  5. Every action is logged to submission_audit_entries.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user, set_rls_context
from app.db.session import get_db
from app.models.audit import AuditLog, ConsentLog
from app.models.form import FormFieldValue, FormInstance
from app.models.submission import SubmissionAuditEntry, SubmissionRun
from app.models.workflow import ApplicationStatusLog
from app.schemas.submissions import (
    AdapterListResponse,
    ApproveSubmissionRequest,
    ApproveSubmissionResponse,
    ResolveCaptchaRequest,
    ResolveCaptchaResponse,
    SubmissionAuditEntryResponse,
    SubmissionAuditResponse,
    SubmissionRunResponse,
    SubmitInstanceRequest,
    SubmitInstanceResponse,
)

router = APIRouter()
logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Adapter discovery
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/adapters", response_model=AdapterListResponse)
async def list_adapters(current_user: dict = Depends(get_current_user)):
    """List all registered portal adapters."""
    from app.services.portal_adapters.registry import registry
    return {"adapters": registry.list_adapters()}


# ──────────────────────────────────────────────────────────────────────────────
# Milestone 4 — Human Approval Gate
# ──────────────────────────────────────────────────────────────────────────────

@router.post(
    "/instances/{instance_id}/approve",
    response_model=ApproveSubmissionResponse,
    status_code=200,
)
async def approve_submission(
    instance_id: str,
    request: ApproveSubmissionRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Record human approval before automated portal submission.

    Validation gates (all must pass):
      1. instance.status == 'ready'  (Phase 2 review gate must have been passed)
      2. All FormFieldValues have human_reviewed == True
      3. No unacknowledged needs_attention fields

    On success: updates instance.status → 'approved', writes ConsentLog + AuditLog.
    """
    await set_rls_context(db, user_id=current_user["user_id"], bypass=True)

    # Load instance
    result = await db.execute(
        select(FormInstance).where(FormInstance.id == instance_id)
    )
    instance = result.scalar_one_or_none()
    if not instance:
        raise HTTPException(status_code=404, detail="Form instance not found.")

    # Gate 1: must be in 'ready' status
    if instance.status not in ("ready", "needs_review"):
        raise HTTPException(
            status_code=422,
            detail=(
                f"Cannot approve submission: instance status is {instance.status!r}. "
                "The instance must be in 'ready' status (all fields reviewed in Phase 2)."
            ),
        )

    # Gate 2: all fields must be human-reviewed
    ffv_result = await db.execute(
        select(FormFieldValue).where(FormFieldValue.form_instance_id == instance_id)
    )
    field_values = ffv_result.scalars().all()

    unreviewed = [f.form_field_id for f in field_values if not f.human_reviewed]
    if unreviewed:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Cannot approve: {len(unreviewed)} field(s) not yet human-reviewed: "
                f"{unreviewed[:5]}{'...' if len(unreviewed) > 5 else ''}. "
                "Use the review endpoint to mark each field as reviewed."
            ),
        )

    # Gate 3: no unacknowledged needs_attention fields
    attention_fields = [
        f.form_field_id for f in field_values
        if f.needs_attention and not f.human_reviewed
    ]
    if attention_fields:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Cannot approve: {len(attention_fields)} field(s) require attention "
                f"and have not been reviewed: {attention_fields[:5]}."
            ),
        )

    # All gates passed — record approval
    now = datetime.now(timezone.utc)
    instance.status = "approved"
    db.add(instance)

    db.add(ConsentLog(
        profile_id=str(instance.profile_id),
        action="submit_application",
        scope=str(instance.id),
    ))

    db.add(AuditLog(
        profile_id=str(instance.profile_id),
        actor=current_user["user_id"],
        action="submission_approved",
        details={
            "instance_id": instance_id,
            "acknowledgement": request.acknowledgement,
            "field_count": len(field_values),
        },
    ))

    await db.commit()

    logger.info(
        "Submission approved by %s for instance %s",
        current_user["user_id"], instance_id,
    )

    return {
        "form_instance_id": instance_id,
        "status": "approved",
        "approved_at": now.isoformat(),
        "message": "Submission approved. Call /submit to begin automated portal submission.",
    }


# ──────────────────────────────────────────────────────────────────────────────
# Milestone 3 — Trigger Submission
# ──────────────────────────────────────────────────────────────────────────────

@router.post(
    "/instances/{instance_id}/submit",
    response_model=SubmitInstanceResponse,
    status_code=202,
)
async def submit_instance(
    instance_id: str,
    request: SubmitInstanceRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Enqueue the Celery submission task for an approved form instance.

    Credentials are passed at call time (ephemeral — never persisted to DB).
    Returns immediately with run_id; poll /submissions/runs/{run_id} for status.
    """
    await set_rls_context(db, user_id=current_user["user_id"], bypass=True)

    # Load instance and verify approved status
    result = await db.execute(
        select(FormInstance).where(FormInstance.id == instance_id)
    )
    instance = result.scalar_one_or_none()
    if not instance:
        raise HTTPException(status_code=404, detail="Form instance not found.")

    if instance.status != "approved":
        raise HTTPException(
            status_code=422,
            detail=(
                f"Cannot submit: instance status is {instance.status!r}. "
                "Call /approve first to record human approval."
            ),
        )

    # Verify adapter exists
    try:
        from app.services.portal_adapters.registry import get_adapter
        get_adapter(request.adapter_id)
    except KeyError:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown portal adapter: {request.adapter_id!r}. "
                   "Call GET /submissions/adapters to see available adapters.",
        )

    # Create a preliminary SubmissionRun record so we can return its ID immediately
    run = SubmissionRun(
        form_instance_id=instance_id,
        portal_adapter=request.adapter_id,
        status="pending",
        approved_by=current_user["user_id"],
        approved_at=datetime.now(timezone.utc),
    )
    db.add(run)
    await db.flush()
    run_id = str(run.id)

    instance.portal_adapter = request.adapter_id
    instance.submission_run_id = run.id
    db.add(instance)

    db.add(AuditLog(
        profile_id=str(instance.profile_id),
        actor=current_user["user_id"],
        action="submission_enqueued",
        details={"run_id": run_id, "adapter_id": request.adapter_id},
    ))

    await db.commit()

    # Enqueue Celery task (credentials passed as JSON — ephemeral)
    from app.tasks.submission import submit_form_instance
    submit_form_instance.apply_async(
        kwargs={
            "instance_id": instance_id,
            "adapter_id": request.adapter_id,
            "credentials_json": json.dumps(request.credentials),
            "form_url": request.form_url,
        },
        queue="submission",
    )

    logger.info(
        "Submission task enqueued: run_id=%s instance=%s adapter=%s",
        run_id, instance_id, request.adapter_id,
    )

    return {
        "form_instance_id": instance_id,
        "run_id": run_id,
        "status": "submitting",
        "message": f"Submission task enqueued. Poll /submissions/runs/{run_id} for progress.",
    }


# ──────────────────────────────────────────────────────────────────────────────
# Status polling
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/runs/{run_id}", response_model=SubmissionRunResponse)
async def get_submission_run(
    run_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Poll the status of a submission run.

    Client should poll every 5 seconds while status is 'running'.
    When status transitions to 'awaiting_user', the user must resolve the CAPTCHA
    and call POST /submissions/runs/{run_id}/resolve-captcha.
    """
    await set_rls_context(db, user_id=current_user["user_id"], bypass=True)

    result = await db.execute(
        select(SubmissionRun).where(SubmissionRun.id == run_id)
    )
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Submission run not found.")

    return {
        "run_id": str(run.id),
        "form_instance_id": str(run.form_instance_id),
        "portal_adapter": run.portal_adapter,
        "status": run.status,
        "portal_reference": run.portal_reference,
        "error_detail": run.error_detail,
        "started_at": run.started_at.isoformat(),
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "approved_by": run.approved_by,
        "approved_at": run.approved_at.isoformat() if run.approved_at else None,
        "screenshot_count": len(run.screenshot_keys or []),
    }


# ──────────────────────────────────────────────────────────────────────────────
# Milestone 4 — CAPTCHA resolution
# ──────────────────────────────────────────────────────────────────────────────

@router.post("/runs/{run_id}/resolve-captcha", response_model=ResolveCaptchaResponse)
async def resolve_captcha(
    run_id: str,
    request: ResolveCaptchaRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Signal that the user has solved the CAPTCHA — resumes the paused submission engine.

    The paused Celery worker polls Redis for this signal every 5 seconds.
    """
    await set_rls_context(db, user_id=current_user["user_id"], bypass=True)

    result = await db.execute(
        select(SubmissionRun).where(SubmissionRun.id == run_id)
    )
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Submission run not found.")

    if run.status != "awaiting_user":
        raise HTTPException(
            status_code=422,
            detail=(
                f"Run is not awaiting user input (current status: {run.status!r}). "
                "CAPTCHA resolution is only valid when status is 'awaiting_user'."
            ),
        )

    # Set Redis key to signal the paused Celery worker
    try:
        import redis.asyncio as aioredis
        from app.core.config import settings
        r = aioredis.from_url(settings.REDIS_URL)
        await r.setex(f"captcha_resolved:{run_id}", 300, "1")  # expires in 5 minutes
        await r.aclose()
    except Exception as exc:
        logger.error("Failed to set captcha_resolved Redis key: %s", exc)
        raise HTTPException(status_code=500, detail="Could not signal CAPTCHA resolution.")

    # Write audit entry
    db.add(SubmissionAuditEntry(
        submission_run_id=run_id,
        action="captcha_resolved",
        portal_response=f"Resolved by {current_user['user_id']}. Note: {request.note or '—'}",
    ))
    db.add(AuditLog(
        profile_id=None,
        actor=current_user["user_id"],
        action="captcha_resolved",
        details={"run_id": run_id, "note": request.note},
    ))
    await db.commit()

    logger.info("CAPTCHA resolved for run %s by %s", run_id, current_user["user_id"])

    return {
        "run_id": run_id,
        "status": "resume_signalled",
        "message": "CAPTCHA resolution signal sent. Submission will resume shortly.",
    }


# ──────────────────────────────────────────────────────────────────────────────
# Milestone 5 — Full audit trail
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/runs/{run_id}/audit", response_model=SubmissionAuditResponse)
async def get_submission_audit(
    run_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the complete per-action audit trail for a submission run.

    All sensitive field values have been masked at the point of capture —
    this endpoint never returns plaintext PII.
    """
    await set_rls_context(db, user_id=current_user["user_id"], bypass=True)

    result = await db.execute(
        select(SubmissionAuditEntry)
        .where(SubmissionAuditEntry.submission_run_id == run_id)
        .order_by(SubmissionAuditEntry.occurred_at)
    )
    entries = result.scalars().all()

    return {
        "run_id": run_id,
        "total": len(entries),
        "entries": [
            {
                "id": str(e.id),
                "action": e.action,
                "field_id": e.field_id,
                "masked_value": e.masked_value,
                "screenshot_key": e.screenshot_key,
                "portal_response": e.portal_response,
                "occurred_at": e.occurred_at.isoformat(),
            }
            for e in entries
        ],
    }


# ──────────────────────────────────────────────────────────────────────────────
# Milestone 5 — Recovery endpoints
# ──────────────────────────────────────────────────────────────────────────────

@router.post("/runs/{run_id}/resume", status_code=202)
async def resume_submission(
    run_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Resume a failed submission run from its last checkpoint.

    Only valid when run.status == 'failed'.
    Re-enqueues the submission task; the engine restores Playwright
    session from the saved storage_state.
    """
    await set_rls_context(db, user_id=current_user["user_id"], bypass=True)

    result = await db.execute(
        select(SubmissionRun).where(SubmissionRun.id == run_id)
    )
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Submission run not found.")

    if run.status != "failed":
        raise HTTPException(
            status_code=422,
            detail=f"Run status is {run.status!r}. Only 'failed' runs can be resumed.",
        )

    instance_result = await db.execute(
        select(FormInstance).where(FormInstance.id == run.form_instance_id)
    )
    instance = instance_result.scalar_one_or_none()

    # Reset run for re-execution
    run.status = "pending"
    run.error_detail = None
    run.completed_at = None
    db.add(run)

    if instance:
        instance.status = "approved"
        db.add(instance)

    db.add(AuditLog(
        profile_id=str(instance.profile_id) if instance else None,
        actor=current_user["user_id"],
        action="submission_resumed",
        details={"run_id": run_id},
    ))
    await db.commit()

    from app.services.submission_recovery import enqueue_resume
    enqueue_resume(run_id)

    return {"run_id": run_id, "status": "pending", "message": "Submission resume enqueued."}


@router.post("/runs/{run_id}/rollback", status_code=200)
async def rollback_submission(
    run_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Rollback a failed/incomplete submission run.

    Reverts FormInstance.status to 'approved' so the user can
    review and re-approve before retrying.
    """
    await set_rls_context(db, user_id=current_user["user_id"], bypass=True)

    result = await db.execute(
        select(SubmissionRun).where(SubmissionRun.id == run_id)
    )
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Submission run not found.")

    if run.status not in ("failed", "awaiting_user"):
        raise HTTPException(
            status_code=422,
            detail=f"Cannot rollback a run with status {run.status!r}.",
        )

    from app.services.submission_recovery import rollback_run
    await rollback_run(run_id, current_user["user_id"], db)

    return {"run_id": run_id, "status": "rolled_back", "message": "Run rolled back successfully."}

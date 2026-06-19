"""Application tracking endpoints."""

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user, set_rls_context
from app.db.session import get_db
from app.models.form import FormInstance
from app.models.workflow import ApplicationStatusLog
from app.models.audit import AuditLog

from app.schemas.applications import (
    UpdateStatusRequest, ApplicationListResponse, 
    StatusUpdateResponse, ApplicationTimelineResponse
)

router = APIRouter()

VALID_STATUSES = {"draft", "filled", "awaiting_review", "submitted", "under_process", "approved", "rejected"}


@router.get("", response_model=ApplicationListResponse)
async def list_applications(
    profile_id: str = Query(...),
    status: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all applications for a profile with optional status filter."""
    await set_rls_context(db, user_id=current_user["user_id"], profile_id=profile_id)

    from app.models.form import FormTemplate
    query = (
        select(FormInstance, FormTemplate.scheme_name)
        .join(FormTemplate, FormInstance.form_template_id == FormTemplate.id)
        .where(FormInstance.profile_id == profile_id)
    )
    if status:
        query = query.where(FormInstance.status == status)
    query = query.order_by(FormInstance.created_at.desc())

    result = await db.execute(query)
    rows = result.fetchall()

    return {
        "applications": [
            {
                "form_instance_id": str(row.FormInstance.id),
                "scheme_name": row.scheme_name,
                "status": row.FormInstance.status,
                "created_at": row.FormInstance.created_at.isoformat(),
                "submitted_at": row.FormInstance.submitted_at.isoformat() if row.FormInstance.submitted_at else None,
                "reference_number": row.FormInstance.reference_number,
            }
            for row in rows
        ]
    }


@router.patch("/{form_instance_id}/status", response_model=StatusUpdateResponse)
async def update_application_status(
    form_instance_id: str,
    request: UpdateStatusRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Manually update application status (for portals without tracking API)."""
    await set_rls_context(db, user_id=current_user["user_id"], bypass=True)

    if request.status not in VALID_STATUSES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid status. Valid options: {sorted(VALID_STATUSES)}",
        )

    result = await db.execute(select(FormInstance).where(FormInstance.id == form_instance_id))
    instance = result.scalar_one_or_none()
    if not instance:
        raise HTTPException(status_code=404, detail="Application not found")

    old_status = instance.status
    instance.status = request.status

    # Log status change
    db.add(ApplicationStatusLog(
        form_instance_id=form_instance_id,
        status=request.status,
        note=request.note,
        changed_by=current_user["user_id"],
    ))

    db.add(AuditLog(
        profile_id=str(instance.profile_id),
        actor=current_user["user_id"],
        action="application_status_updated",
        details={"old": old_status, "new": request.status, "note": request.note},
    ))

    return {"form_instance_id": form_instance_id, "status": request.status}


@router.get("/{form_instance_id}/timeline", response_model=ApplicationTimelineResponse)
async def get_application_timeline(
    form_instance_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get full status history for an application."""
    await set_rls_context(db, user_id=current_user["user_id"], bypass=True)

    result = await db.execute(
        select(ApplicationStatusLog)
        .where(ApplicationStatusLog.form_instance_id == form_instance_id)
        .order_by(ApplicationStatusLog.changed_at)
    )
    logs = result.scalars().all()

    return {
        "form_instance_id": form_instance_id,
        "timeline": [
            {
                "status": log.status,
                "note": log.note,
                "changed_by": log.changed_by,
                "changed_at": log.changed_at.isoformat(),
            }
            for log in logs
        ],
    }

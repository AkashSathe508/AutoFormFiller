"""Submission Recovery Service — Phase 3.

Provides functions to resume or rollback failed submission runs.
"""

import logging
import json
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.submission import SubmissionRun, SubmissionAuditEntry
from app.models.form import FormInstance
from app.models.audit import AuditLog

logger = logging.getLogger(__name__)


def enqueue_resume(run_id: str) -> None:
    """Re-enqueue a failed submission task to resume from its checkpoint.

    Must be called AFTER the SubmissionRun status has been reset to 'pending'
    and the FormInstance status reverted to 'approved'.
    """
    from app.tasks.submission import submit_form_instance
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.core.config import settings

    engine = create_engine(settings.DATABASE_SYNC_URL)
    Session = sessionmaker(bind=engine)

    with Session() as db:
        run = db.query(SubmissionRun).filter(SubmissionRun.id == run_id).first()
        if not run:
            logger.error("Cannot enqueue resume: run %s not found", run_id)
            return

        instance = db.query(FormInstance).filter(FormInstance.id == run.form_instance_id).first()
        if not instance:
            logger.error("Cannot enqueue resume: instance %s not found", run.form_instance_id)
            return

        adapter_id = run.portal_adapter
        instance_id = str(instance.id)

    # Note: credentials are required to resume. The API endpoint handling the
    # resume request should technically accept them again since they are ephemeral.
    # For Phase 3 MVP, we assume the resume endpoint asks for them or we retry
    # without them (if already logged in via storage_state). We pass empty for now.
    logger.info("Re-enqueuing submission run %s", run_id)

    submit_form_instance.apply_async(
        kwargs={
            "instance_id": instance_id,
            "adapter_id": adapter_id,
            "credentials_json": "{}",  # Needs to be provided by resume API in a real implementation
            "form_url": "",
        },
        queue="submission",
    )


async def rollback_run(run_id: str, user_id: str, db: AsyncSession) -> None:
    """Rollback a failed/incomplete submission run.

    Reverts the FormInstance to 'approved' so it can be reviewed
    and re-approved for a fresh submission attempt.
    """
    result = await db.execute(select(SubmissionRun).where(SubmissionRun.id == run_id))
    run = result.scalar_one_or_none()
    if not run:
        return

    instance_result = await db.execute(select(FormInstance).where(FormInstance.id == run.form_instance_id))
    instance = instance_result.scalar_one_or_none()

    old_status = run.status
    run.status = "failed"
    run.error_detail = "Rolled back by user."
    db.add(run)

    if instance:
        instance.status = "approved"
        db.add(instance)

    db.add(SubmissionAuditEntry(
        submission_run_id=run_id,
        action="error",
        portal_response=f"Run rolled back by user {user_id}. Previous status: {old_status}",
    ))

    db.add(AuditLog(
        profile_id=str(instance.profile_id) if instance else None,
        actor=user_id,
        action="submission_rolled_back",
        details={"run_id": run_id, "previous_status": old_status},
    ))

    await db.commit()
    logger.info("Rolled back submission run %s", run_id)

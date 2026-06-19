"""Phase 3 — Celery submission task.

Drives the full portal submission pipeline:
  1. Load + decrypt FormFieldValue records
  2. Hard-assert human approval gate
  3. Create SubmissionRun record
  4. Run SubmissionEngine (Playwright) via the registered portal adapter
  5. Update FormInstance status + reference number
  6. Write ApplicationStatusLog + AuditLog

Queue: 'submission' (separate from ocr/prefill to isolate long-running Playwright jobs)

The task is intentionally synchronous (no async Celery) because Playwright's
async_api is managed internally by the engine using asyncio.run().
"""

from __future__ import annotations

import asyncio
import logging
import json
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from app.celery_app import celery_app
from app.core.config import settings

logger = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    name="app.tasks.submission.submit_form_instance",
    max_retries=0,          # Submission is not auto-retried — human must re-approve
    queue="submission",
    soft_time_limit=360,    # 6 minutes soft limit (engine has 5-min internal hard limit)
    time_limit=420,         # 7 minutes hard kill
)
def submit_form_instance(
    self,
    instance_id: str,
    adapter_id: str,
    credentials_json: str,
    form_url: str = "",
) -> dict:
    """Submit a pre-approved FormInstance through a portal adapter.

    Args:
        instance_id:      UUID of the FormInstance to submit.
        adapter_id:       Registry ID of the portal adapter (e.g. 'mock_portal').
        credentials_json: JSON-serialised portal credentials (ephemeral — not persisted).
        form_url:         URL of the specific form on the portal (may be empty for
                          adapters that navigate internally after login).

    Returns:
        dict with keys: success, portal_reference, run_id, error.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.models.form import FormInstance, FormFieldValue
    from app.models.submission import SubmissionRun, SubmissionAuditEntry
    from app.models.workflow import WorkflowRun, ApplicationStatusLog
    from app.models.audit import AuditLog, ConsentLog
    from app.models.document import Document
    from app.core.encryption import decrypt_field, unwrap_dek
    from app.services.portal_adapters.registry import get_adapter
    from app.services.submission_engine import SubmissionEngine, StepCheckpoint

    engine = create_engine(settings.DATABASE_SYNC_URL)
    Session = sessionmaker(bind=engine)
    credentials = json.loads(credentials_json)

    with Session() as db:
        # ── 1. Load FormInstance ──────────────────────────────────────
        instance = db.query(FormInstance).filter(
            FormInstance.id == instance_id
        ).first()

        if not instance:
            raise ValueError(f"FormInstance {instance_id} not found.")

        if instance.status != "approved":
            raise ValueError(
                f"FormInstance {instance_id} is not approved for submission "
                f"(current status: {instance.status!r}). "
                "Human approval is mandatory before submission."
            )

        profile_id = str(instance.profile_id)

        # ── 2. Load profile DEK ───────────────────────────────────────
        # Use the most recent verified document's DEK for decryption
        doc = (
            db.query(Document)
            .filter(
                Document.profile_id == profile_id,
                Document.is_current == True,
                Document.processing_status == "verified",
            )
            .order_by(Document.uploaded_at.desc())
            .first()
        )
        profile_dek: Optional[bytes] = None
        if doc:
            try:
                profile_dek = unwrap_dek(doc.encryption_key_id)
            except Exception as exc:
                logger.warning("Could not unwrap DEK for profile %s: %s", profile_id, exc)

        # ── 3. Decrypt field values ───────────────────────────────────
        field_values: dict[str, str] = {}
        ffvs = (
            db.query(FormFieldValue)
            .filter(FormFieldValue.form_instance_id == instance_id)
            .all()
        )
        for ffv in ffvs:
            if not ffv.value_encrypted:
                continue
            try:
                if profile_dek:
                    plain = decrypt_field(ffv.value_encrypted, profile_dek, ffv.form_field_id)
                else:
                    plain = ffv.value_encrypted   # already plaintext (test/dev mode)
                field_values[ffv.form_field_id] = plain
            except Exception as exc:
                logger.warning("Decrypt failed for field %s: %s", ffv.form_field_id, exc)

        # ── 4. Load upload slots from form template ───────────────────
        from app.models.form import FormTemplate
        template = db.query(FormTemplate).filter(
            FormTemplate.id == instance.form_template_id
        ).first()
        upload_slots: list[dict] = template.upload_slots if template else []

        # ── 5. Create SubmissionRun ───────────────────────────────────
        run = SubmissionRun(
            form_instance_id=instance_id,
            portal_adapter=adapter_id,
            status="running",
        )
        db.add(run)
        db.flush()
        run_id = str(run.id)

        # Link run to instance
        instance.portal_adapter = adapter_id
        instance.submission_run_id = run.id
        instance.status = "submitting"
        db.add(instance)

        # Update workflow state
        if instance.workflow_run_id:
            wf = db.query(WorkflowRun).filter(
                WorkflowRun.id == instance.workflow_run_id
            ).first()
            if wf:
                _append_workflow_history(wf, "SUBMITTING")
                wf.current_state = "SUBMITTING"
                db.add(wf)

        db.commit()
        logger.info("SubmissionRun %s created for instance %s", run_id, instance_id)

    # ── 6. Run the Playwright engine (outside the DB session) ─────────
    # Callbacks communicate back to the DB within the engine execution.

    def _make_minio_client():
        import boto3
        from botocore.client import Config
        return boto3.client(
            "s3",
            endpoint_url=settings.MINIO_ENDPOINT,
            aws_access_key_id=settings.MINIO_ACCESS_KEY,
            aws_secret_access_key=settings.MINIO_SECRET_KEY,
            config=Config(signature_version="s3v4"),
        )

    minio_client = _make_minio_client()
    _ensure_bucket_exists(minio_client, "submission-artifacts")

    # ── Audit callback ────────────────────────────────────────────────
    def _sync_audit(action, field_id=None, masked_value=None,
                    screenshot_key=None, portal_response=None, extra=None):
        with Session() as db2:
            entry = SubmissionAuditEntry(
                submission_run_id=run_id,
                action=action,
                field_id=field_id,
                masked_value=masked_value,
                screenshot_key=screenshot_key,
                portal_response=portal_response,
                extra=extra or {},
            )
            db2.add(entry)
            # Also append screenshot key to run's array
            if screenshot_key:
                db2.execute(
                    __import__("sqlalchemy").text(
                        "UPDATE submission_runs SET screenshot_keys = "
                        "array_append(screenshot_keys, :key) WHERE id = :rid"
                    ),
                    {"key": screenshot_key, "rid": run_id},
                )
            db2.commit()

    async def audit_cb(**kwargs):
        _sync_audit(**kwargs)

    # ── Captcha resolution callback ───────────────────────────────────
    def _is_captcha_resolved() -> bool:
        """Check Redis for a captcha-resolved signal for this run."""
        try:
            import redis
            r = redis.from_url(settings.REDIS_URL)
            key = f"captcha_resolved:{run_id}"
            result = r.get(key)
            if result:
                r.delete(key)
                return True
        except Exception as exc:
            logger.warning("Redis captcha check failed: %s", exc)
        return False

    async def captcha_check_cb() -> bool:
        return _is_captcha_resolved()

    # ── Checkpoint save callback ──────────────────────────────────────
    def _save_checkpoint(cp: StepCheckpoint):
        with Session() as db3:
            db3.execute(
                __import__("sqlalchemy").text(
                    "UPDATE submission_runs SET checkpoint = :cp WHERE id = :rid"
                ),
                {"cp": json.dumps({
                    "last_completed_step": cp.last_completed_step,
                    "field_fill_index": cp.field_fill_index,
                    "storage_state": cp.storage_state,
                    "extra": cp.extra,
                }), "rid": run_id},
            )
            db3.commit()

    async def checkpoint_save_cb(cp: StepCheckpoint):
        _save_checkpoint(cp)

    # ── Handle CAPTCHA wait — update run status while paused ──────────
    original_captcha_check = captcha_check_cb

    async def captcha_check_with_status_update() -> bool:
        with Session() as db4:
            db4.execute(
                __import__("sqlalchemy").text(
                    "UPDATE submission_runs SET status = 'awaiting_user' WHERE id = :rid"
                ),
                {"rid": run_id},
            )
            db4.commit()
        return await original_captcha_check()

    # ── Execute ───────────────────────────────────────────────────────
    adapter = get_adapter(adapter_id)
    engine_obj = SubmissionEngine(
        run_id=run_id,
        minio_client=minio_client,
        audit_callback=audit_cb,
        captcha_check_callback=captcha_check_with_status_update,
        checkpoint_save_callback=checkpoint_save_cb,
        headless=getattr(settings, "PLAYWRIGHT_HEADLESS", True),
    )

    submission_result = asyncio.run(
        engine_obj.run(
            adapter=adapter,
            field_values=field_values,
            upload_slots=upload_slots,
            credentials=credentials,
            form_url=form_url,
        )
    )

    # ── 7. Persist final result ───────────────────────────────────────
    with Session() as db:
        run_obj = db.query(SubmissionRun).filter(SubmissionRun.id == run_id).first()
        instance = db.query(FormInstance).filter(
            FormInstance.id == instance_id
        ).first()

        now = datetime.now(timezone.utc)

        if submission_result.success:
            run_obj.status = "completed"
            run_obj.portal_reference = submission_result.portal_reference
            run_obj.completed_at = now

            instance.status = "submitted"
            instance.submitted_at = now
            instance.reference_number = submission_result.portal_reference

            # Update workflow
            if instance.workflow_run_id:
                wf = db.query(WorkflowRun).filter(
                    WorkflowRun.id == instance.workflow_run_id
                ).first()
                if wf:
                    _append_workflow_history(wf, "SUBMITTED")
                    wf.current_state = "SUBMITTED"
                    db.add(wf)

            db.add(ApplicationStatusLog(
                form_instance_id=instance_id,
                status="submitted",
                note=f"Submitted via {adapter_id}. Ref: {submission_result.portal_reference}",
                changed_by="system:submission_agent",
            ))

        else:
            run_obj.status = "failed"
            run_obj.error_detail = submission_result.error
            run_obj.completed_at = now

            instance.status = "approved"   # revert — keep approval, allow re-submit

            if instance.workflow_run_id:
                wf = db.query(WorkflowRun).filter(
                    WorkflowRun.id == instance.workflow_run_id
                ).first()
                if wf:
                    _append_workflow_history(wf, "FAILED")
                    wf.current_state = "FAILED"
                    db.add(wf)

            db.add(ApplicationStatusLog(
                form_instance_id=instance_id,
                status="failed",
                note=f"Submission failed: {submission_result.error}",
                changed_by="system:submission_agent",
            ))

        db.add(AuditLog(
            profile_id=profile_id,
            actor="system:submission_agent",
            action="form_submitted" if submission_result.success else "submission_failed",
            details={
                "run_id": run_id,
                "adapter_id": adapter_id,
                "portal_reference": submission_result.portal_reference,
                "error": submission_result.error,
            },
        ))

        db.add(run_obj)
        db.add(instance)
        db.commit()

    logger.info(
        "Submission run %s finished: success=%s ref=%s",
        run_id, submission_result.success, submission_result.portal_reference,
    )

    return {
        "success": submission_result.success,
        "portal_reference": submission_result.portal_reference,
        "run_id": run_id,
        "error": submission_result.error,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _append_workflow_history(wf, new_state: str) -> None:
    """Append a state transition entry to the workflow history JSON array."""
    history = list(wf.history or [])
    history.append({
        "state": new_state,
        "at": datetime.now(timezone.utc).isoformat(),
        "actor": "system:submission_agent",
    })
    wf.history = history


def _ensure_bucket_exists(minio_client, bucket: str) -> None:
    """Create the MinIO bucket if it doesn't exist."""
    try:
        minio_client.head_bucket(Bucket=bucket)
    except Exception:
        try:
            minio_client.create_bucket(Bucket=bucket)
            logger.info("Created MinIO bucket: %s", bucket)
        except Exception as exc:
            logger.warning("Could not create bucket %r: %s", bucket, exc)

"""Playwright Submission Engine — Phase 3.

Manages the full browser lifecycle for automated portal submissions:
  - Chromium launch/close
  - Session persistence via storage_state
  - Per-step retry with exponential backoff
  - Screenshot capture after every significant action
  - CAPTCHA detection → AWAITING_USER pause
  - Checkpoint-based resumption after failure
  - Hard 5-minute timeout per submission run

Usage (called from the Celery submission task):
    engine = SubmissionEngine(run_id, minio_client, db)
    result = await engine.run(adapter, field_values, upload_slots, credentials)
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from app.services.portal_adapters.base import (
    CaptchaAction,
    PortalAdapter,
    SubmissionResult,
)
from app.services.portal_adapters.utils import (
    detect_form_error,
    mask_sensitive_value,
    safe_screenshot,
)

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────────────

SUBMISSION_TIMEOUT_SECONDS = 300    # 5-minute hard limit per run
STEP_RETRY_MAX = 3                  # retries per individual step
STEP_RETRY_BASE_DELAY = 2.0         # seconds (doubles each retry)
MINIO_SCREENSHOTS_BUCKET = "submission-artifacts"
CAPTCHA_RESUME_POLL_INTERVAL = 5.0  # seconds between polls for captcha resolution


# ──────────────────────────────────────────────────────────────────────────────
# Engine state
# ──────────────────────────────────────────────────────────────────────────────

class EngineStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    AWAITING_USER = "awaiting_user"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class StepCheckpoint:
    """Snapshot of progress for checkpoint-based resumption."""
    last_completed_step: str = ""       # step name (e.g. 'login', 'fill_fields')
    storage_state: Optional[dict] = None  # Playwright browser storage state JSON
    field_fill_index: int = 0           # index into field_values list for partial fills
    extra: dict = field(default_factory=dict)


# ──────────────────────────────────────────────────────────────────────────────
# Audit callback type
# ──────────────────────────────────────────────────────────────────────────────

class SubmissionEngine:
    """Manages browser lifecycle and step execution for portal submissions.

    Args:
        run_id:        UUID of the SubmissionRun row.
        minio_client:  Initialised boto3 / MinIO S3 client for screenshot uploads.
        audit_callback: Async callable(action, field_id, masked_value,
                        screenshot_key, portal_response, extra) persists each
                        action to submission_audit_entries.
        captcha_check_callback: Async callable() → bool. Returns True if the
                                Celery worker should resume (user resolved CAPTCHA).
        checkpoint_save_callback: Async callable(StepCheckpoint). Persists the
                                  checkpoint to submission_runs.checkpoint.
        headless: Whether to run Chromium headless (default True).
    """

    def __init__(
        self,
        run_id: str,
        minio_client: Any,
        audit_callback: Any,
        captcha_check_callback: Any,
        checkpoint_save_callback: Any,
        headless: bool = True,
    ):
        self.run_id = run_id
        self.minio_client = minio_client
        self.audit_callback = audit_callback
        self.captcha_check_callback = captcha_check_callback
        self.checkpoint_save_callback = checkpoint_save_callback
        self.headless = headless
        self.status = EngineStatus.IDLE
        self._browser: Any = None
        self._context: Any = None

    # ──────────────────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────────────────

    async def run(
        self,
        adapter: PortalAdapter,
        field_values: dict[str, str],
        upload_slots: list[dict],
        credentials: dict,
        form_url: str = "",
        checkpoint: Optional[StepCheckpoint] = None,
    ) -> SubmissionResult:
        """Execute the full submission pipeline with timeout enforcement.

        Returns a SubmissionResult regardless of success/failure — callers
        inspect `.success` rather than catching exceptions.
        """
        self.status = EngineStatus.RUNNING

        try:
            result = await asyncio.wait_for(
                self._execute_pipeline(
                    adapter, field_values, upload_slots,
                    credentials, form_url, checkpoint,
                ),
                timeout=SUBMISSION_TIMEOUT_SECONDS,
            )
            self.status = EngineStatus.COMPLETED
            return result

        except asyncio.TimeoutError:
            logger.error(
                "Submission run %s timed out after %ds.",
                self.run_id, SUBMISSION_TIMEOUT_SECONDS,
            )
            self.status = EngineStatus.FAILED
            return SubmissionResult(success=False, error="Submission timed out after 5 minutes.")

        except Exception as exc:  # noqa: BLE001
            logger.exception("Submission run %s failed with unexpected error.", self.run_id)
            self.status = EngineStatus.FAILED
            return SubmissionResult(success=False, error=str(exc))

        finally:
            await self._close_browser()

    # ──────────────────────────────────────────────────────────────────────
    # Pipeline
    # ──────────────────────────────────────────────────────────────────────

    async def _execute_pipeline(
        self,
        adapter: PortalAdapter,
        field_values: dict[str, str],
        upload_slots: list[dict],
        credentials: dict,
        form_url: str,
        checkpoint: Optional[StepCheckpoint],
    ) -> SubmissionResult:
        """Inner pipeline — sequenced steps with checkpoint awareness."""

        await self._launch_browser(
            storage_state=checkpoint.storage_state if checkpoint else None
        )
        page = await self._context.new_page()
        completed_steps = {checkpoint.last_completed_step} if checkpoint else set()

        # ── Step 1: Login ──────────────────────────────────────────────
        if "login" not in completed_steps:
            await self._audit("navigate", extra={"url": adapter.portal_url})
            success = await self._retry_step("login", lambda: adapter.login(page, credentials))
            if not success:
                screenshot_key = await safe_screenshot(
                    page, self.run_id, "login_failed", self.minio_client, MINIO_SCREENSHOTS_BUCKET
                )
                await self._audit("error", screenshot_key=screenshot_key,
                                  portal_response="Login failed")
                return SubmissionResult(success=False, error="Portal login failed.")

            screenshot_key = await safe_screenshot(
                page, self.run_id, "login_success", self.minio_client, MINIO_SCREENSHOTS_BUCKET
            )
            await self._audit("navigate", screenshot_key=screenshot_key,
                              portal_response="Login successful")
            await self._save_checkpoint(page, "login")

        # ── Step 2: Load form ──────────────────────────────────────────
        if "load_form" not in completed_steps:
            success = await self._retry_step(
                "load_form", lambda: adapter.load_form(page, form_url)
            )
            if not success:
                screenshot_key = await safe_screenshot(
                    page, self.run_id, "load_form_failed", self.minio_client, MINIO_SCREENSHOTS_BUCKET
                )
                await self._audit("error", screenshot_key=screenshot_key,
                                  portal_response="Form failed to load")
                return SubmissionResult(success=False, error="Could not load form page.")

            screenshot_key = await safe_screenshot(
                page, self.run_id, "form_loaded", self.minio_client, MINIO_SCREENSHOTS_BUCKET
            )
            await self._audit("navigate", screenshot_key=screenshot_key,
                              portal_response="Form page loaded")
            await self._save_checkpoint(page, "load_form")

        # Check CAPTCHA after navigation
        captcha_result = await self._handle_captcha_if_present(adapter, page)
        if captcha_result is not None:
            return captcha_result

        # ── Step 3: Fill fields ────────────────────────────────────────
        if "fill_fields" not in completed_steps:
            start_index = checkpoint.field_fill_index if checkpoint else 0
            fill_results = await adapter.fill_fields(
                page,
                {k: v for i, (k, v) in enumerate(field_values.items()) if i >= start_index},
            )

            for fr in fill_results:
                masked = mask_sensitive_value(fr.field_id, fr.masked_value or "")
                await self._audit(
                    "fill_field",
                    field_id=fr.field_id,
                    masked_value=masked,
                    portal_response=fr.error if not fr.success else None,
                )

            failed_fills = [r for r in fill_results if not r.success]
            if failed_fills:
                logger.warning(
                    "Run %s: %d field(s) failed to fill: %s",
                    self.run_id,
                    len(failed_fills),
                    [r.field_id for r in failed_fills],
                )

            screenshot_key = await safe_screenshot(
                page, self.run_id, "fields_filled", self.minio_client, MINIO_SCREENSHOTS_BUCKET
            )
            await self._audit("fill_field", screenshot_key=screenshot_key,
                              portal_response=f"Filled {len(fill_results)} fields")
            await self._save_checkpoint(page, "fill_fields")

        # Check CAPTCHA after filling
        captcha_result = await self._handle_captcha_if_present(adapter, page)
        if captcha_result is not None:
            return captcha_result

        # ── Step 4: Upload documents ───────────────────────────────────
        if "upload_documents" not in completed_steps and upload_slots:
            upload_results = await adapter.upload_documents(page, upload_slots)

            for ur in upload_results:
                await self._audit(
                    "upload_document",
                    field_id=ur.slot_id,
                    masked_value=ur.filename,
                    portal_response=ur.error if not ur.success else "uploaded",
                )

            screenshot_key = await safe_screenshot(
                page, self.run_id, "uploads_done", self.minio_client, MINIO_SCREENSHOTS_BUCKET
            )
            await self._audit("upload_document", screenshot_key=screenshot_key)
            await self._save_checkpoint(page, "upload_documents")

        # ── Step 5: Validate ───────────────────────────────────────────
        if "validate" not in completed_steps:
            validation = await adapter.validate(page)
            if not validation.passed:
                screenshot_key = await safe_screenshot(
                    page, self.run_id, "validation_failed", self.minio_client, MINIO_SCREENSHOTS_BUCKET
                )
                await self._audit(
                    "error",
                    screenshot_key=screenshot_key,
                    portal_response="; ".join(validation.errors),
                )
                return SubmissionResult(
                    success=False,
                    error=f"Portal validation failed: {'; '.join(validation.errors)}",
                )
            await self._save_checkpoint(page, "validate")

        # ── Step 6: Submit ─────────────────────────────────────────────
        screenshot_key = await safe_screenshot(
            page, self.run_id, "pre_submit", self.minio_client, MINIO_SCREENSHOTS_BUCKET
        )
        await self._audit("submit_clicked", screenshot_key=screenshot_key)

        submission_result = await adapter.submit(page)

        final_screenshot_key = await safe_screenshot(
            page, self.run_id, "post_submit", self.minio_client, MINIO_SCREENSHOTS_BUCKET
        )
        submission_result.confirmation_screenshot_key = final_screenshot_key

        await self._audit(
            "portal_response",
            screenshot_key=final_screenshot_key,
            portal_response=(
                submission_result.portal_reference or submission_result.error or "no response"
            ),
        )

        return submission_result

    # ──────────────────────────────────────────────────────────────────────
    # CAPTCHA handling
    # ──────────────────────────────────────────────────────────────────────

    async def _handle_captcha_if_present(
        self, adapter: PortalAdapter, page: Any
    ) -> Optional[SubmissionResult]:
        """If a CAPTCHA is detected, pause and wait for human resolution.

        Returns None if no CAPTCHA or if resolved.
        Returns a SubmissionResult(success=False) if the wait is abandoned.
        """
        if not await adapter.is_captcha_present(page):
            return None

        screenshot_key = await safe_screenshot(
            page, self.run_id, "captcha_detected", self.minio_client, MINIO_SCREENSHOTS_BUCKET
        )
        await self._audit("captcha_detected", screenshot_key=screenshot_key,
                          portal_response="CAPTCHA detected — pausing for human")

        self.status = EngineStatus.AWAITING_USER
        action = await adapter.handle_captcha(page)  # always returns PAUSE_FOR_USER

        # Poll for resolution signal (set via Redis pub/sub by the API endpoint)
        resolved = await self._poll_for_captcha_resolution()

        if not resolved:
            return SubmissionResult(
                success=False,
                error="CAPTCHA was not resolved within the allowed timeout.",
            )

        self.status = EngineStatus.RUNNING
        await self._audit("captcha_resolved", portal_response="User resolved CAPTCHA")
        return None

    async def _poll_for_captcha_resolution(self, max_wait_seconds: int = 600) -> bool:
        """Poll the captcha_check_callback every N seconds until resolved or timed out."""
        elapsed = 0
        while elapsed < max_wait_seconds:
            resolved = await self.captcha_check_callback()
            if resolved:
                return True
            await asyncio.sleep(CAPTCHA_RESUME_POLL_INTERVAL)
            elapsed += CAPTCHA_RESUME_POLL_INTERVAL
        return False

    # ──────────────────────────────────────────────────────────────────────
    # Retry helper
    # ──────────────────────────────────────────────────────────────────────

    async def _retry_step(self, step_name: str, coro_fn) -> Any:
        """Execute coro_fn with up to STEP_RETRY_MAX retries."""
        delay = STEP_RETRY_BASE_DELAY
        for attempt in range(1, STEP_RETRY_MAX + 1):
            try:
                result = await coro_fn()
                if result is not False:
                    return result
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Step %r attempt %d/%d failed: %s",
                    step_name, attempt, STEP_RETRY_MAX, exc,
                )
            if attempt < STEP_RETRY_MAX:
                await asyncio.sleep(delay)
                delay *= 2
        return False

    # ──────────────────────────────────────────────────────────────────────
    # Browser lifecycle
    # ──────────────────────────────────────────────────────────────────────

    async def _launch_browser(self, storage_state: Optional[dict] = None) -> None:
        """Start Playwright Chromium. Reuses storage_state for session resumption."""
        from playwright.async_api import async_playwright

        playwright = await async_playwright().start()
        self._playwright = playwright
        self._browser = await playwright.chromium.launch(
            headless=self.headless,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        context_kwargs: dict = {
            "viewport": {"width": 1280, "height": 900},
            "user_agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
        }
        if storage_state:
            context_kwargs["storage_state"] = storage_state

        self._context = await self._browser.new_context(**context_kwargs)
        logger.debug("Chromium launched (headless=%s) for run %s", self.headless, self.run_id)

    async def _close_browser(self) -> None:
        """Gracefully close browser and Playwright instance."""
        try:
            if self._context:
                await self._context.close()
            if self._browser:
                await self._browser.close()
            if hasattr(self, "_playwright"):
                await self._playwright.stop()
        except Exception:  # noqa: BLE001
            pass

    # ──────────────────────────────────────────────────────────────────────
    # Checkpoint
    # ──────────────────────────────────────────────────────────────────────

    async def _save_checkpoint(self, page: Any, step_name: str) -> None:
        """Persist browser state + step name for resumption."""
        try:
            storage_state = await self._context.storage_state()
            cp = StepCheckpoint(
                last_completed_step=step_name,
                storage_state=storage_state,
            )
            await self.checkpoint_save_callback(cp)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Checkpoint save failed at step %r: %s", step_name, exc)

    # ──────────────────────────────────────────────────────────────────────
    # Audit
    # ──────────────────────────────────────────────────────────────────────

    async def _audit(
        self,
        action: str,
        field_id: Optional[str] = None,
        masked_value: Optional[str] = None,
        screenshot_key: Optional[str] = None,
        portal_response: Optional[str] = None,
        extra: Optional[dict] = None,
    ) -> None:
        """Persist one audit entry via the injected callback."""
        try:
            await self.audit_callback(
                action=action,
                field_id=field_id,
                masked_value=masked_value,
                screenshot_key=screenshot_key,
                portal_response=portal_response,
                extra=extra or {},
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Audit callback failed: %s", exc)

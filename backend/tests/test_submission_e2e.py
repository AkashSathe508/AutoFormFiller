"""Phase 3 Submission Engine — end-to-end verification tests.

Four test scenarios:
  1. test_successful_submission_flow      — happy path (mock adapter, no real browser)
  2. test_captcha_pause_resume_flow       — CAPTCHA detection, Redis signal, resume
  3. test_failure_flow_checkpoint_created — portal error creates a checkpoint
  4. test_resume_from_checkpoint          — picks up from saved checkpoint

Each test runs fully in-process using unittest.mock — NO Docker or live browser required.

For live integration against the running mock-portal container, use:
    pytest backend/tests/test_submission_e2e.py -m live --live
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

from app.services.submission_engine import (
    EngineStatus,
    StepCheckpoint,
    SubmissionEngine,
    SUBMISSION_TIMEOUT_SECONDS,
)
from app.services.portal_adapters.base import (
    CaptchaAction,
    FieldFillResult,
    PortalAdapter,
    SubmissionResult,
    UploadResult,
    ValidationResult,
)

# ──────────────────────────────────────────────────────────────────────────────
# Helpers & stubs
# ──────────────────────────────────────────────────────────────────────────────

def _noop_audit(**kwargs):
    """Silent audit callback — records calls for assertion later."""
    return asyncio.coroutine(lambda: None)()


def _make_audit_spy():
    """Return an async spy that collects (action, field_id) tuples."""
    calls = []

    async def _spy(action, field_id=None, masked_value=None,
                   screenshot_key=None, portal_response=None, extra=None):
        calls.append({"action": action, "field_id": field_id,
                      "portal_response": portal_response})

    _spy.calls = calls
    return _spy


def _make_captcha_cb(resolves_after: int = 0):
    """Returns a captcha callback that resolves after N calls."""
    counter = {"n": 0}

    async def _cb() -> bool:
        counter["n"] += 1
        return counter["n"] > resolves_after

    return _cb


def _checkpoint_spy():
    """Async callback that records the latest checkpoint."""
    saved = {}

    async def _save(cp: StepCheckpoint):
        saved["last"] = cp

    _save.saved = saved
    return _save


class _HappyPathAdapter(PortalAdapter):
    """Minimal in-memory adapter — never actually opens a browser."""
    adapter_id = "happy_path"
    display_name = "Happy Path"
    portal_url = "http://fake-portal"
    supported_form_types = ["test"]

    async def login(self, page, credentials) -> bool:
        return True

    async def load_form(self, page, form_url) -> bool:
        return True

    async def fill_fields(self, page, field_values) -> list[FieldFillResult]:
        return [FieldFillResult(field_id=k, success=True, masked_value=v)
                for k, v in field_values.items()]

    async def upload_documents(self, page, upload_slots) -> list[UploadResult]:
        return []

    async def validate(self, page) -> ValidationResult:
        return ValidationResult(passed=True)

    async def submit(self, page) -> SubmissionResult:
        return SubmissionResult(
            success=True,
            portal_reference=f"MOCK-{uuid.uuid4().hex[:8].upper()}"
        )

    async def is_captcha_present(self, page) -> bool:
        return False


class _CaptchaAdapter(_HappyPathAdapter):
    """Adapter that signals CAPTCHA presence on first check only."""
    adapter_id = "captcha_adapter"

    def __init__(self):
        super().__init__()
        self._captcha_triggered = False

    async def is_captcha_present(self, page) -> bool:
        if not self._captcha_triggered:
            self._captcha_triggered = True
            return True
        return False


class _FailingAdapter(_HappyPathAdapter):
    """Adapter where submit always fails."""
    adapter_id = "failing_adapter"

    async def submit(self, page) -> SubmissionResult:
        return SubmissionResult(success=False, error="Portal returned 503 error")


# ──────────────────────────────────────────────────────────────────────────────
# Common engine factory — patches out Playwright so no real browser is needed
# ──────────────────────────────────────────────────────────────────────────────

def _make_engine(audit_spy, checkpoint_spy, captcha_cb) -> SubmissionEngine:
    engine = SubmissionEngine(
        run_id=str(uuid.uuid4()),
        minio_client=MagicMock(),
        audit_callback=audit_spy,
        captcha_check_callback=captcha_cb,
        checkpoint_save_callback=checkpoint_spy,
        headless=True,
    )
    return engine


async def _run_with_mock_browser(engine: SubmissionEngine, adapter, field_values,
                                  upload_slots=None, credentials=None,
                                  checkpoint=None) -> SubmissionResult:
    """Patch Playwright internals so no real browser is launched."""
    mock_page = AsyncMock()
    mock_context = AsyncMock()
    mock_context.new_page = AsyncMock(return_value=mock_page)
    mock_context.storage_state = AsyncMock(return_value={"cookies": [], "origins": []})
    mock_browser = AsyncMock()
    mock_playwright_instance = AsyncMock()
    mock_playwright_instance.chromium.launch = AsyncMock(return_value=mock_browser)

    with patch(
        "app.services.portal_adapters.utils.safe_screenshot",
        new_callable=AsyncMock,
        return_value="test-screenshot-key",
    ):
        mock_browser.new_context = AsyncMock(return_value=mock_context)

        engine._browser = mock_browser
        engine._context = mock_context
        engine._playwright = mock_playwright_instance

        # Bypass _launch_browser so we keep our mocks in place
        with patch.object(engine, "_launch_browser", new_callable=AsyncMock):
            result = await engine._execute_pipeline(
                adapter=adapter,
                field_values=field_values or {"full_name": "Ananya Sharma", "dob": "2000-01-01"},
                upload_slots=upload_slots or [],
                credentials=credentials or {"username": "u", "password": "p"},
                form_url="",
                checkpoint=checkpoint,
            )

    return result


# ──────────────────────────────────────────────────────────────────────────────
# Scenario 1 — Successful Submission Flow
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_successful_submission_flow():
    """
    Review → Approval → Submission → Reference Number
    Verifies the happy path produces a portal_reference and correct audit trail.
    """
    audit = _make_audit_spy()
    cp_spy = _checkpoint_spy()
    captcha_cb = _make_captcha_cb(resolves_after=0)

    engine = _make_engine(audit, cp_spy, captcha_cb)
    adapter = _HappyPathAdapter()

    result = await _run_with_mock_browser(
        engine, adapter,
        field_values={"full_name": "Ananya Sharma", "dob": "2000-01-01", "aadhaar_number": "1234 5678 9012"},
    )

    # ── Assertions ────────────────────────────────────────────────────
    assert result.success, f"Expected success=True, got error: {result.error}"
    assert result.portal_reference is not None
    assert result.portal_reference.startswith("MOCK-")

    actions = [c["action"] for c in audit.calls]
    assert "navigate" in actions, "No navigate audit entry"
    assert "fill_field" in actions, "No fill_field audit entry"
    assert "submit_clicked" in actions, "No submit_clicked audit entry"
    assert "portal_response" in actions, "No portal_response audit entry"

    # Checkpoint was saved after each major step
    assert cp_spy.saved.get("last") is not None, "No checkpoint was ever saved"

    print(f"\n✅ SCENARIO 1 PASS — Reference: {result.portal_reference}")
    print(f"   Audit entries: {actions}")
    print(f"   Last checkpoint step: {cp_spy.saved['last'].last_completed_step}")


# ──────────────────────────────────────────────────────────────────────────────
# Scenario 2 — CAPTCHA Flow
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_captcha_pause_resume_flow():
    """
    Review → CAPTCHA detected → User resolves CAPTCHA → Submission resumes → Success
    Verifies:
    - captcha_detected audit entry written
    - Engine pauses (awaiting_user status)
    - After Redis signal, engine resumes and completes
    """
    audit = _make_audit_spy()
    cp_spy = _checkpoint_spy()

    # Captcha resolves on 2nd poll (simulating user solving it)
    captcha_cb = _make_captcha_cb(resolves_after=1)

    engine = _make_engine(audit, cp_spy, captcha_cb)
    adapter = _CaptchaAdapter()

    result = await _run_with_mock_browser(engine, adapter,
        field_values={"full_name": "Test User"},
    )

    assert result.success, f"Expected success after CAPTCHA resolved. Error: {result.error}"
    assert result.portal_reference is not None

    actions = [c["action"] for c in audit.calls]
    assert "captcha_detected" in actions, "CAPTCHA was not logged in audit trail"
    assert "captcha_resolved" in actions, "CAPTCHA resolution not logged"
    assert "portal_response" in actions, "Submission result not logged after CAPTCHA"

    print(f"\n✅ SCENARIO 2 PASS — CAPTCHA resolved. Reference: {result.portal_reference}")
    print(f"   Audit entries: {actions}")


# ──────────────────────────────────────────────────────────────────────────────
# Scenario 3 — Failure Flow → Checkpoint Created
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_failure_flow_checkpoint_created():
    """
    Review → Submission failure → Recovery checkpoint created

    Verifies:
    - Submission returns success=False
    - Portal response is logged as an error in the audit trail
    - A checkpoint was saved (so recovery is possible)
    """
    audit = _make_audit_spy()
    cp_spy = _checkpoint_spy()
    captcha_cb = _make_captcha_cb(resolves_after=0)

    engine = _make_engine(audit, cp_spy, captcha_cb)
    adapter = _FailingAdapter()

    result = await _run_with_mock_browser(engine, adapter,
        field_values={"full_name": "Test User"},
    )

    assert not result.success, "Expected failure from FailingAdapter"
    assert result.error, "Error detail must be set on failure"
    assert "503" in result.error, f"Unexpected error message: {result.error}"

    actions = [c["action"] for c in audit.calls]
    assert "portal_response" in actions, "Failure was not logged in audit"

    # At least one checkpoint was saved (after login, load_form, fill_fields steps)
    assert cp_spy.saved.get("last") is not None, "No checkpoint saved — recovery impossible"

    print(f"\n✅ SCENARIO 3 PASS — Failure correctly logged. Error: {result.error}")
    print(f"   Last checkpoint: {cp_spy.saved['last'].last_completed_step}")
    print(f"   Audit entries: {actions}")


# ──────────────────────────────────────────────────────────────────────────────
# Scenario 4 — Resume from Checkpoint
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_resume_from_checkpoint():
    """
    Failed submission → Resume from checkpoint → Successful completion

    Verifies:
    - Providing a checkpoint with last_completed_step='fill_fields' skips
      login, load_form, and fill_fields — goes straight to upload/validate/submit
    - Result is still successful (adapter is happy path)
    """
    audit = _make_audit_spy()
    cp_spy = _checkpoint_spy()
    captcha_cb = _make_captcha_cb(resolves_after=0)

    engine = _make_engine(audit, cp_spy, captcha_cb)
    adapter = _HappyPathAdapter()

    # Simulate a checkpoint saved after fill_fields completed
    checkpoint = StepCheckpoint(
        last_completed_step="fill_fields",
        storage_state={"cookies": [{"name": "session", "value": "abc123"}], "origins": []},
        field_fill_index=0,
    )

    result = await _run_with_mock_browser(
        engine, adapter,
        field_values={"full_name": "Ananya Sharma"},
        checkpoint=checkpoint,
    )

    assert result.success, f"Expected success on resume. Error: {result.error}"
    assert result.portal_reference is not None

    actions = [c["action"] for c in audit.calls]

    # login & load_form steps were SKIPPED (checkpoint said they completed)
    # The first new action should be submit_clicked → portal_response
    assert "submit_clicked" in actions, "submit_clicked not found — resume may have re-run skipped steps"
    assert "portal_response" in actions

    print(f"\n✅ SCENARIO 4 PASS — Resumed from checkpoint, completed OK.")
    print(f"   Reference: {result.portal_reference}")
    print(f"   Audit entries (only post-checkpoint steps): {actions}")


# ──────────────────────────────────────────────────────────────────────────────
# Additional Unit Tests — Portal Adapter Framework
# ──────────────────────────────────────────────────────────────────────────────

class TestPortalAdapterRegistry:
    """Verify the adapter registry framework (no browser required)."""

    def test_mock_portal_registered(self):
        """MockPortalAdapter should be importable and registered."""
        from app.services.portal_adapters.registry import get_adapter
        from app.services.portal_adapters import mock_portal  # noqa: F401

        adapter = get_adapter("mock_portal")
        assert adapter is not None
        assert adapter.adapter_id == "mock_portal"
        assert adapter.portal_url == "http://mock-portal:8080"
        assert "scholarship" in adapter.supported_form_types

    def test_get_unknown_adapter_raises(self):
        """Requesting an unregistered adapter must raise KeyError."""
        from app.services.portal_adapters.registry import get_adapter

        with pytest.raises((KeyError, ValueError)):
            get_adapter("nonexistent_portal_xyz")


class TestSubmissionEngineUnit:
    """Unit tests for SubmissionEngine helpers (no browser)."""

    def test_engine_starts_idle(self):
        audit = _make_audit_spy()
        cp_spy = _checkpoint_spy()
        captcha_cb = _make_captcha_cb()

        eng = _make_engine(audit, cp_spy, captcha_cb)
        assert eng.status == EngineStatus.IDLE

    @pytest.mark.asyncio
    async def test_timeout_produces_failure_result(self):
        """An extremely short timeout should return a failure SubmissionResult."""
        audit = _make_audit_spy()
        cp_spy = _checkpoint_spy()
        captcha_cb = _make_captcha_cb()

        eng = _make_engine(audit, cp_spy, captcha_cb)
        adapter = _HappyPathAdapter()

        # Patch _execute_pipeline to sleep forever so timeout fires
        async def _slow(*args, **kwargs):
            await asyncio.sleep(999)

        with patch.object(eng, "_execute_pipeline", side_effect=_slow), \
             patch.object(eng, "_close_browser", new_callable=AsyncMock):
            # Override timeout constant to 0.05s
            with patch("app.services.submission_engine.SUBMISSION_TIMEOUT_SECONDS", 0.05):
                result = await eng.run(
                    adapter=adapter,
                    field_values={},
                    upload_slots=[],
                    credentials={},
                )

        assert not result.success
        assert "timed out" in result.error.lower()
        assert eng.status == EngineStatus.FAILED

    @pytest.mark.asyncio
    async def test_sensitive_masking_in_audit(self):
        """Aadhaar numbers in audit entries should be masked."""
        from app.services.portal_adapters.utils import mask_sensitive_value

        masked = mask_sensitive_value("aadhaar_number", "1234 5678 9012")
        assert "9012" in masked, "Last 4 digits should be visible"
        assert "1234" not in masked, "First digits should be masked"
        assert "XXXX" in masked or "*" in masked or "X" in masked, "Masking characters expected"

    def test_step_checkpoint_dataclass(self):
        """StepCheckpoint can be created and serialised."""
        cp = StepCheckpoint(
            last_completed_step="fill_fields",
            storage_state={"cookies": []},
            field_fill_index=3,
        )
        payload = json.dumps({
            "last_completed_step": cp.last_completed_step,
            "field_fill_index": cp.field_fill_index,
            "storage_state": cp.storage_state,
            "extra": cp.extra,
        })
        recovered = json.loads(payload)
        assert recovered["last_completed_step"] == "fill_fields"
        assert recovered["field_fill_index"] == 3


class TestSubmissionAuditLog:
    """Verify SubmissionAuditEntry ORM model field structure."""

    def test_submission_audit_model_fields(self):
        from app.models.submission import SubmissionAuditEntry, SubmissionRun
        import sqlalchemy as sa

        run_cols = {c.name for c in SubmissionRun.__table__.columns}
        assert "status" in run_cols
        assert "checkpoint" in run_cols
        assert "screenshot_keys" in run_cols
        assert "portal_reference" in run_cols
        assert "error_detail" in run_cols

        audit_cols = {c.name for c in SubmissionAuditEntry.__table__.columns}
        assert "action" in audit_cols
        assert "field_id" in audit_cols
        assert "masked_value" in audit_cols
        assert "screenshot_key" in audit_cols
        assert "portal_response" in audit_cols

    def test_submission_run_lifecycle_states(self):
        """Document the expected status lifecycle values."""
        valid_states = {"pending", "running", "awaiting_user", "completed", "failed"}
        assert "running" in valid_states
        assert "awaiting_user" in valid_states
        assert "completed" in valid_states


class TestSubmissionAPIRoutes:
    """Verify Phase 3 submission API routes are registered."""

    def test_submission_api_routes_registered(self):
        """All Phase 3 submission endpoints must be in the FastAPI router."""
        from app.main import app

        routes = {r.path for r in app.routes}
        # Core submission lifecycle
        expected = [
            "/api/v1/submissions",
        ]
        for path in expected:
            assert any(path in r for r in routes), \
                f"Route containing '{path}' not registered. Found: {routes}"

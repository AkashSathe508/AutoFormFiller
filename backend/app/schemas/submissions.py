"""Pydantic schemas for Phase 3 submission endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ──────────────────────────────────────────────────────────────────────────────
# Request schemas
# ──────────────────────────────────────────────────────────────────────────────

class ApproveSubmissionRequest(BaseModel):
    """Request body for POST /submissions/instances/{id}/approve."""

    # No body fields required — the approval is the act of calling the endpoint.
    # Optional: capture a freetext acknowledgement note.
    acknowledgement: Optional[str] = Field(
        None,
        description="Optional human acknowledgement note recorded in audit log.",
        max_length=500,
    )


class SubmitInstanceRequest(BaseModel):
    """Request body for POST /submissions/instances/{id}/submit."""

    adapter_id: str = Field(
        ...,
        description="Portal adapter identifier (e.g. 'mock_portal').",
        example="mock_portal",
    )
    credentials: Dict[str, str] = Field(
        ...,
        description=(
            "Portal login credentials. Ephemeral — never persisted. "
            "Keys are adapter-specific (e.g. {'username': ..., 'password': ...})."
        ),
    )
    form_url: str = Field(
        "",
        description="URL of the specific form page (may be empty for adapters that navigate internally).",
    )


class ResolveCaptchaRequest(BaseModel):
    """Request body for POST /submissions/runs/{run_id}/resolve-captcha."""

    note: Optional[str] = Field(
        None,
        description="Optional note about how the CAPTCHA was resolved.",
        max_length=200,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Response schemas
# ──────────────────────────────────────────────────────────────────────────────

class ApproveSubmissionResponse(BaseModel):
    form_instance_id: str
    status: str
    approved_at: str
    message: str


class SubmitInstanceResponse(BaseModel):
    form_instance_id: str
    run_id: str
    status: str = "submitting"
    message: str = "Submission task enqueued. Poll /submissions/runs/{run_id} for progress."


class SubmissionRunResponse(BaseModel):
    run_id: str
    form_instance_id: str
    portal_adapter: str
    status: str
    portal_reference: Optional[str] = None
    error_detail: Optional[str] = None
    started_at: str
    completed_at: Optional[str] = None
    approved_by: Optional[str] = None
    approved_at: Optional[str] = None
    screenshot_count: int = 0


class SubmissionAuditEntryResponse(BaseModel):
    id: str
    action: str
    field_id: Optional[str] = None
    masked_value: Optional[str] = None
    screenshot_key: Optional[str] = None
    portal_response: Optional[str] = None
    occurred_at: str


class SubmissionAuditResponse(BaseModel):
    run_id: str
    entries: List[SubmissionAuditEntryResponse]
    total: int


class ResolveCaptchaResponse(BaseModel):
    run_id: str
    status: str = "resume_signalled"
    message: str = "CAPTCHA resolution signal sent. Submission will resume shortly."


class AdapterListResponse(BaseModel):
    adapters: List[Dict[str, Any]]

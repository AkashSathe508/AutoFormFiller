"""Pydantic schemas for the Forms API — Phase 2."""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, field_validator


# ──────────────────────────────────────────────────────────────────────────────
# Request schemas
# ──────────────────────────────────────────────────────────────────────────────

class ParseFormRequest(BaseModel):
    """Submit a web URL for form parsing."""
    url: str
    scheme_name: Optional[str] = None


class CreateInstanceRequest(BaseModel):
    """Create a pre-filled form instance for a profile."""
    form_template_id: str
    profile_id: str


class UpdateFieldRequest(BaseModel):
    """Human review: override a single pre-filled field value."""
    form_field_id: str
    value: str  # Plain-text value; API will encrypt before storing


class ApproveInstanceRequest(BaseModel):
    """Approve a form instance for submission after human review."""
    override_attention: bool = False  # True to approve despite remaining attention flags


# ──────────────────────────────────────────────────────────────────────────────
# Field-level schemas
# ──────────────────────────────────────────────────────────────────────────────

class FormFieldSchema(BaseModel):
    """A single field definition from a parsed form template."""
    field_id: str
    label: str
    field_type: str   # text | number | date | select | checkbox | radio | file | signature | textarea
    required: bool = False
    read_only: bool = False
    options: Optional[List[str]] = None
    max_length: Optional[int] = None
    profile_field_hint: Optional[str] = None  # LLM-suggested profile key from parse step
    position: Optional[Dict[str, Any]] = None  # AcroForm bounding box


class UploadSlotSchema(BaseModel):
    """A document upload slot detected in the form."""
    slot_id: str
    label: str
    accepted_formats: List[str] = []
    max_size_kb: Optional[int] = None


# ──────────────────────────────────────────────────────────────────────────────
# Template response schemas
# ──────────────────────────────────────────────────────────────────────────────

class FormTemplateResponse(BaseModel):
    """Summary or detailed response for a FormTemplate."""
    id: str
    source_type: str
    source_url_or_hash: str
    scheme_name: Optional[str] = None
    version: int = 1
    field_count: int
    upload_slot_count: int = 0
    parse_method: Optional[str] = None   # "acroform" | "ocr_llm" | "playwright"
    parsed_at: str
    # Full field schema — populated on GET /forms/{id}, omitted in list views
    fields: Optional[List[FormFieldSchema]] = None
    upload_slots: Optional[List[UploadSlotSchema]] = None
    # Parsing status for async responses
    status: str = "ready"  # "parsing" | "ready" | "failed"


# ──────────────────────────────────────────────────────────────────────────────
# Instance response schemas
# ──────────────────────────────────────────────────────────────────────────────

class FieldValueResponse(BaseModel):
    """A single pre-filled (or human-entered) field value in a form instance."""
    form_field_id: str
    label: Optional[str] = None         # From template field_schema
    field_type: Optional[str] = None    # From template field_schema
    value: Optional[str] = None         # Decrypted value for display
    method: str                         # "rule" | "hint" | "embedding" | "llm" | "cache" | "human" | "none"
    source_field_key: Optional[str] = None  # Which profile field produced this value
    confidence: float = 0.0
    human_reviewed: bool
    needs_attention: bool
    attention_reason: Optional[str] = None
    required: bool = False


class FormInstanceResponse(BaseModel):
    """A form instance with its pre-filled field values."""
    id: str
    form_template_id: str
    profile_id: str
    status: str   # draft | filling | needs_review | ready | approved | submitted | rejected
    created_at: str
    submitted_at: Optional[str] = None
    reference_number: Optional[str] = None
    fields: List[FieldValueResponse] = []
    # Summary counts (convenience for UI)
    total_fields: int = 0
    filled_fields: int = 0
    attention_fields: int = 0


# ──────────────────────────────────────────────────────────────────────────────
# Gap detection schema (Milestone 4)
# ──────────────────────────────────────────────────────────────────────────────

class GapFieldInfo(BaseModel):
    """Details about a single unmapped or attention-requiring field."""
    field_id: str
    label: str
    required: bool = False
    reason: str
    method: str = "none"


class GapReportResponse(BaseModel):
    """Completion report for a form instance — identifies missing/unmapped fields."""
    instance_id: str
    status: str
    total_fields: int
    filled_fields: int
    attention_fields: int
    unmapped_fields: int
    completion_percentage: float
    gaps: List[GapFieldInfo] = []
    can_approve: bool  # True if no required fields are unmapped


# ──────────────────────────────────────────────────────────────────────────────
# Approval schema (Milestone 5)
# ──────────────────────────────────────────────────────────────────────────────

class ApproveInstanceResponse(BaseModel):
    """Response after approving a form instance."""
    instance_id: str
    status: str
    approved_at: str
    attention_fields_remaining: int
    message: str

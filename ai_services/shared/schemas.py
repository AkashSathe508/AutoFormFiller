"""Shared Pydantic contracts between AI agents."""

from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from enum import Enum


class DocType(str, Enum):
    AADHAAR = "AADHAAR"
    PAN = "PAN"
    PASSPORT = "PASSPORT"
    DRIVING_LICENSE = "DRIVING_LICENSE"
    MARKSHEET_10 = "MARKSHEET_10"
    MARKSHEET_12 = "MARKSHEET_12"
    DEGREE_CERTIFICATE = "DEGREE_CERTIFICATE"
    CASTE_CERTIFICATE = "CASTE_CERTIFICATE"
    INCOME_CERTIFICATE = "INCOME_CERTIFICATE"
    UTILITY_BILL = "UTILITY_BILL"
    MEDICAL_DOCUMENT = "MEDICAL_DOCUMENT"
    GOVERNMENT_ID_OTHER = "GOVERNMENT_ID_OTHER"
    UNKNOWN = "UNKNOWN"


class VerificationFlag(str, Enum):
    OK = "ok"
    REVIEW = "review"
    SUSPICIOUS = "suspicious"


class MappingMethod(str, Enum):
    RULE = "rule"
    EMBEDDING = "embedding"
    LLM = "llm"
    USER_MANUAL = "user_manual"


class OCRBlock(BaseModel):
    text: str
    bbox: Optional[List[float]] = None
    confidence: float = 1.0


class OCRResult(BaseModel):
    document_id: str
    text: str
    blocks: List[OCRBlock] = []
    language_detected: str = "en"
    page_count: int = 1
    ocr_confidence: float = 1.0
    model_used: str = "paddleocr"


class ClassificationResult(BaseModel):
    document_id: str
    doc_type: DocType
    confidence: float
    alt_candidates: List[Dict[str, Any]] = []
    method: str = "rule"  # 'rule' or 'llm'


class VerificationCheck(BaseModel):
    check_name: str
    passed: bool
    detail: str


class VerificationResult(BaseModel):
    document_id: str
    checks: List[VerificationCheck]
    overall_flag: VerificationFlag


class FormField(BaseModel):
    field_id: str
    label: str
    field_type: str = "text"  # text, date, number, enum, file_upload, checkbox
    required: bool = False
    constraints: Optional[Dict[str, Any]] = None
    position: Optional[int] = None


class UploadSlot(BaseModel):
    slot_id: str
    label: str
    accepted_formats: List[str] = ["jpeg", "pdf"]
    max_size_kb: Optional[int] = None
    dimensions: Optional[str] = None


class FormSchema(BaseModel):
    form_id: str
    source_type: str
    fields: List[FormField] = []
    upload_slots: List[UploadSlot] = []


class FieldMapping(BaseModel):
    form_field_id: str
    profile_field_key: Optional[str]
    value: Optional[str]
    confidence: float
    method: MappingMethod
    needs_attention: bool = False
    attention_reason: Optional[str] = None


class FillResult(BaseModel):
    form_instance_id: str
    mappings: List[FieldMapping]
    filled_count: int
    unmapped_fields: List[FormField] = []


class WorkflowState(str, Enum):
    UPLOADED = "UPLOADED"
    EXTRACTING = "EXTRACTING"
    VERIFYING = "VERIFYING"
    PROFILE_MERGE_PENDING = "PROFILE_MERGE_PENDING"
    PROFILE_READY = "PROFILE_READY"
    FORM_DETECTED = "FORM_DETECTED"
    MAPPING = "MAPPING"
    GAP_DETECTION = "GAP_DETECTION"
    REVIEW_PENDING = "REVIEW_PENDING"
    SUBMIT_APPROVED = "SUBMIT_APPROVED"
    SUBMITTING = "SUBMITTING"
    SUBMITTED = "SUBMITTED"
    TRACKING = "TRACKING"
    FAILED = "FAILED"

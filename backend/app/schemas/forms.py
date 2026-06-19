from typing import List, Optional
from pydantic import BaseModel, HttpUrl

class ParseFormRequest(BaseModel):
    url: str
    scheme_name: Optional[str] = None


class FormFieldSchema(BaseModel):
    field_id: str
    label: str
    field_type: str
    required: bool = False
    options: Optional[List[str]] = None
    max_length: Optional[int] = None


class FormTemplateResponse(BaseModel):
    id: str
    source_type: str
    source_url_or_hash: str
    scheme_name: Optional[str]
    field_count: int
    parsed_at: str


class CreateInstanceRequest(BaseModel):
    form_template_id: str
    profile_id: str


class FieldValueResponse(BaseModel):
    form_field_id: str
    value: Optional[str]           # decrypted for display
    method: str
    human_reviewed: bool
    needs_attention: bool
    attention_reason: Optional[str]


class FormInstanceResponse(BaseModel):
    id: str
    form_template_id: str
    profile_id: str
    status: str
    created_at: str
    submitted_at: Optional[str]
    reference_number: Optional[str]
    fields: List[FieldValueResponse] = []


class UpdateFieldRequest(BaseModel):
    form_field_id: str
    value: str

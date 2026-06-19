from typing import Optional, List
from pydantic import BaseModel

class DocumentUploadResponse(BaseModel):
    document_id: str
    status: str

class DocumentStatusResponse(BaseModel):
    document_id: str
    doc_type: str
    status: str
    verification_flag: Optional[str]
    extracted_fields_preview: List[str]
    uploaded_at: str

class DocumentMetadata(BaseModel):
    document_id: str
    doc_type: str
    mime_type: str
    size_bytes: int
    version: int
    uploaded_at: str
    expires_hint_at: Optional[str]

class DocumentListResponse(BaseModel):
    documents: List[DocumentMetadata]

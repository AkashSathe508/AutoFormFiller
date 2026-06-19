from typing import List, Optional
from pydantic import BaseModel

class UpdateStatusRequest(BaseModel):
    status: str
    note: Optional[str] = None

class ApplicationMetadata(BaseModel):
    form_instance_id: str
    scheme_name: Optional[str]
    status: str
    created_at: str
    submitted_at: Optional[str]
    reference_number: Optional[str]

class ApplicationListResponse(BaseModel):
    applications: List[ApplicationMetadata]

class StatusUpdateResponse(BaseModel):
    form_instance_id: str
    status: str

class TimelineEvent(BaseModel):
    status: str
    note: Optional[str]
    changed_by: str
    changed_at: str

class ApplicationTimelineResponse(BaseModel):
    form_instance_id: str
    timeline: List[TimelineEvent]

from pydantic import BaseModel

class CreateProfileRequest(BaseModel):
    display_name: str
    relation_to_account: str = "self"


class ProfileResponse(BaseModel):
    profile_id: str
    display_name: str
    relation_to_account: str

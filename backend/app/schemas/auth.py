from typing import Optional
from pydantic import BaseModel, field_validator

class RegisterRequest(BaseModel):
    email: Optional[str] = None
    phone: Optional[str] = None
    password: str
    display_name: str

    @field_validator('email')
    @classmethod
    def validate_email(cls, v):
        if v and '@' not in v:
            raise ValueError('Invalid email address')
        return v

    @field_validator('phone')
    @classmethod
    def validate_phone(cls, v):
        if v and not v.startswith('+'):
            raise ValueError('Phone must start with country code, e.g. +919876543210')
        return v


class LoginRequest(BaseModel):
    email: Optional[str] = None
    phone: Optional[str] = None
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class RefreshRequest(BaseModel):
    refresh_token: str


class OTPVerifyRequest(BaseModel):
    user_id: str
    otp: str
    purpose: str = "phone_verification"

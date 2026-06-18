"""Authentication endpoints."""

import hashlib
import random
import string
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status, Request
from pydantic import BaseModel, EmailStr, field_validator
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import (
    hash_password, verify_password,
    create_access_token, create_refresh_token,
    decode_token, validate_password_strength, set_rls_context
)
from app.db.session import get_db
from app.models.user import User, Profile
from app.models.auth import OtpToken, RefreshToken

router = APIRouter()


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


def generate_otp(length: int = 6) -> str:
    return ''.join(random.choices(string.digits, k=length))


async def send_otp(user_id: str, otp: str, contact: str, db: AsyncSession) -> None:
    """Send OTP via configured provider. Console in dev."""
    otp_hash = hashlib.sha256(otp.encode()).hexdigest()
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=settings.OTP_TTL_SECONDS)

    # Invalidate previous OTPs for this user+purpose
    await db.execute(
        update(OtpToken)
        .where(OtpToken.user_id == user_id, OtpToken.purpose == "phone_verification", OtpToken.used == False)
        .values(used=True)
    )

    token = OtpToken(
        user_id=user_id,
        token_hash=otp_hash,
        purpose="phone_verification",
        expires_at=expires_at,
    )
    db.add(token)

    if settings.OTP_PROVIDER == "console":
        print(f"\n{'='*50}")
        print(f"OTP for {contact}: {otp}")
        print(f"{'='*50}\n")
    # Add SMS providers here (Twilio, MSG91, etc.) for production


@router.post("/register", status_code=201)
async def register(
    request: RegisterRequest,
    db: AsyncSession = Depends(get_db),
):
    """Register a new user account."""
    await set_rls_context(db, bypass=True)

    # Validate at least one contact method
    if not request.email and not request.phone:
        raise HTTPException(status_code=422, detail="Email or phone number is required")

    validate_password_strength(request.password)

    # Check for existing user
    if request.email:
        result = await db.execute(select(User).where(User.email == request.email))
        if result.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="Email already registered")

    if request.phone:
        result = await db.execute(select(User).where(User.phone == request.phone))
        if result.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="Phone number already registered")

    # Create user
    user = User(
        email=request.email,
        phone=request.phone,
        password_hash=hash_password(request.password),
        role="user",
        is_verified=not bool(request.phone),  # Email users verified immediately in MVP
    )
    db.add(user)
    await db.flush()  # Get user.id

    # Create default 'self' profile
    profile = Profile(
        user_id=user.id,
        display_name=request.display_name,
        relation_to_account="self",
    )
    db.add(profile)
    await db.flush()

    message = "Account created successfully"
    if request.phone:
        otp = generate_otp()
        await send_otp(str(user.id), otp, request.phone, db)
        message = "Verification OTP sent to phone"

    return {"user_id": str(user.id), "profile_id": str(profile.id), "message": message}


@router.post("/login", response_model=TokenResponse)
async def login(
    request: LoginRequest,
    db: AsyncSession = Depends(get_db),
):
    """Login with email/phone + password."""
    await set_rls_context(db, bypass=True)

    if not request.email and not request.phone:
        raise HTTPException(status_code=422, detail="Email or phone required")

    # Fetch user
    if request.email:
        result = await db.execute(select(User).where(User.email == request.email, User.is_active == True))
    else:
        result = await db.execute(select(User).where(User.phone == request.phone, User.is_active == True))

    user = result.scalar_one_or_none()

    if not user or not verify_password(request.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    access_token = create_access_token(str(user.id), user.role)
    refresh_token_str = create_refresh_token(str(user.id))

    # Store refresh token hash
    token_hash = hashlib.sha256(refresh_token_str.encode()).hexdigest()
    rt = RefreshToken(
        user_id=user.id,
        token_hash=token_hash,
        expires_at=datetime.now(timezone.utc) + timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS),
    )
    db.add(rt)

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token_str,
        expires_in=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(
    request: RefreshRequest,
    db: AsyncSession = Depends(get_db),
):
    """Refresh access token using a valid refresh token."""
    await set_rls_context(db, bypass=True)

    payload = decode_token(request.refresh_token)
    if payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    token_hash = hashlib.sha256(request.refresh_token.encode()).hexdigest()
    result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.token_hash == token_hash,
            RefreshToken.revoked == False,
            RefreshToken.expires_at > datetime.now(timezone.utc),
        )
    )
    rt = result.scalar_one_or_none()
    if not rt:
        raise HTTPException(status_code=401, detail="Refresh token expired or revoked")

    user_result = await db.execute(select(User).where(User.id == rt.user_id, User.is_active == True))
    user = user_result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="User not found or inactive")

    # Rotate refresh token
    rt.revoked = True
    new_refresh = create_refresh_token(str(user.id))
    new_hash = hashlib.sha256(new_refresh.encode()).hexdigest()
    new_rt = RefreshToken(
        user_id=user.id,
        token_hash=new_hash,
        expires_at=datetime.now(timezone.utc) + timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS),
    )
    db.add(new_rt)

    return TokenResponse(
        access_token=create_access_token(str(user.id), user.role),
        refresh_token=new_refresh,
        expires_in=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.post("/verify-otp")
async def verify_otp(
    request: OTPVerifyRequest,
    db: AsyncSession = Depends(get_db),
):
    """Verify an OTP for phone verification."""
    await set_rls_context(db, bypass=True)

    otp_hash = hashlib.sha256(request.otp.encode()).hexdigest()
    result = await db.execute(
        select(OtpToken).where(
            OtpToken.user_id == request.user_id,
            OtpToken.token_hash == otp_hash,
            OtpToken.purpose == request.purpose,
            OtpToken.used == False,
            OtpToken.expires_at > datetime.now(timezone.utc),
        )
    )
    token = result.scalar_one_or_none()
    if not token:
        raise HTTPException(status_code=400, detail="Invalid or expired OTP")

    token.used = True

    # Mark user as verified
    user_result = await db.execute(select(User).where(User.id == request.user_id))
    user = user_result.scalar_one_or_none()
    if user:
        user.is_verified = True

    return {"message": "Phone verified successfully"}


@router.post("/logout")
async def logout(
    request: RefreshRequest,
    db: AsyncSession = Depends(get_db),
):
    """Revoke a refresh token (logout)."""
    await set_rls_context(db, bypass=True)

    token_hash = hashlib.sha256(request.refresh_token.encode()).hexdigest()
    result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.token_hash == token_hash,
            RefreshToken.revoked == False,
        )
    )
    rt = result.scalar_one_or_none()
    if rt:
        rt.revoked = True

    return {"message": "Logged out successfully"}

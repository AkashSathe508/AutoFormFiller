"""Authentication, authorization, and JWT management."""

from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHashError
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import get_db

ph = PasswordHasher(
    time_cost=3,
    memory_cost=65536,
    parallelism=1,
    hash_len=32,
    salt_len=16,
)

security_scheme = HTTPBearer()


def hash_password(password: str) -> str:
    """Hash a password using Argon2."""
    return ph.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash."""
    try:
        return ph.verify(hashed_password, plain_password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def create_access_token(user_id: str, role: str = "user") -> str:
    """Create a short-lived JWT access token."""
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES
    )
    payload = {
        "sub": user_id,
        "role": role,
        "type": "access",
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def create_refresh_token(user_id: str) -> str:
    """Create a long-lived JWT refresh token."""
    expire = datetime.now(timezone.utc) + timedelta(
        days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS
    )
    payload = {
        "sub": user_id,
        "type": "refresh",
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    """Decode and validate a JWT token."""
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM]
        )
        return payload
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or expired token: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security_scheme),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """FastAPI dependency: validates JWT and returns current user info."""
    payload = decode_token(credentials.credentials)
    if payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type",
        )
    return {
        "user_id": payload["sub"],
        "role": payload.get("role", "user"),
    }


async def set_rls_context(
    db: AsyncSession,
    user_id: Optional[str] = None,
    profile_id: Optional[str] = None,
    bypass: bool = False,
) -> None:
    """Set Postgres session variables for Row-Level Security."""
    if bypass:
        await db.execute(
            "SELECT set_config('app.bypass_rls', 'true', true)"
        )
    else:
        await db.execute(
            "SELECT set_config('app.bypass_rls', 'false', true)"
        )
    if user_id:
        await db.execute(
            f"SELECT set_config('app.current_user_id', '{user_id}', true)"
        )
    if profile_id:
        await db.execute(
            f"SELECT set_config('app.current_profile_id', '{profile_id}', true)"
        )


def validate_password_strength(password: str) -> None:
    """Enforce password policy: min 12 chars, mixed content."""
    if len(password) < 12:
        raise HTTPException(
            status_code=422,
            detail="Password must be at least 12 characters long",
        )
    has_upper = any(c.isupper() for c in password)
    has_lower = any(c.islower() for c in password)
    has_digit = any(c.isdigit() for c in password)
    has_special = any(c in '!@#$%^&*()_+-=[]{}|;:,.<>?' for c in password)
    if not (has_upper and has_lower and has_digit):
        raise HTTPException(
            status_code=422,
            detail="Password must contain uppercase, lowercase, and a digit",
        )

"""Application configuration using pydantic-settings."""

from typing import List, Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import AnyHttpUrl, field_validator
import json


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # App
    APP_ENV: str = "development"
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000
    FRONTEND_URL: str = "http://localhost:5173"
    BACKEND_CORS_ORIGINS: str = '["http://localhost:5173", "http://localhost:3000"]'

    @property
    def cors_origins(self) -> List[str]:
        try:
            return json.loads(self.BACKEND_CORS_ORIGINS)
        except Exception:
            return [self.BACKEND_CORS_ORIGINS]

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://autoform:autoform_secret@localhost:5432/autoformfiller"
    DATABASE_SYNC_URL: str = "postgresql://autoform:autoform_secret@localhost:5432/autoformfiller"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # MinIO
    MINIO_ENDPOINT: str = "localhost:9000"
    MINIO_ACCESS_KEY: str = "minioadmin"
    MINIO_SECRET_KEY: str = "minioadmin_secret_change_in_prod"
    MINIO_BUCKET: str = "autoformfiller-docs"
    MINIO_USE_SSL: bool = False

    # JWT
    JWT_SECRET: str = "change_this_secret"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    # Encryption (KEK)
    KEK_BASE64: str = ""

    # Ollama / LLM
    OLLAMA_HOST: str = "http://localhost:11434"
    OLLAMA_PRIMARY_MODEL: str = "qwen2.5:7b-instruct-q4_K_M"
    OLLAMA_FALLBACK_MODEL: str = "llama3.1:8b-instruct-q4_K_M"
    OLLAMA_TIMEOUT_SECONDS: int = 120

    # OCR
    OCR_LANG: str = "en+hi"
    OCR_ENGINE: str = "paddleocr"

    # Embeddings
    EMBEDDING_MODEL: str = "intfloat/multilingual-e5-small"
    EMBEDDING_DIM: int = 384
    EMBEDDING_COSINE_THRESHOLD: float = 0.82

    # Celery
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"

    # Rate limiting
    RATE_LIMIT_AUTH: str = "5/minute"
    RATE_LIMIT_UPLOAD: str = "30/hour"

    # OTP
    OTP_PROVIDER: str = "console"
    OTP_TTL_SECONDS: int = 600

    # File upload limits
    MAX_UPLOAD_SIZE_MB: int = 15
    ALLOWED_MIME_TYPES: List[str] = ["image/jpeg", "image/png", "application/pdf"]

    @property
    def max_upload_size_bytes(self) -> int:
        return self.MAX_UPLOAD_SIZE_MB * 1024 * 1024


settings = Settings()

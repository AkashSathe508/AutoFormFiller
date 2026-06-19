"""Shared utilities for portal adapters.

Provides:
  - mask_sensitive_value()   — PII masking before audit logging
  - safe_screenshot()        — screenshot capture + MinIO upload
  - wait_for_navigation()    — shared retry/timeout wrapper
  - detect_form_error()      — generic error banner detection
"""

from __future__ import annotations

import io
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Fields whose values must be masked in audit logs
_SENSITIVE_FIELD_PATTERNS = [
    "aadhaar", "uid", "pan", "passport", "password", "dob",
    "date_of_birth", "account", "ifsc", "bank", "income",
    "mobile", "phone", "email",
]

# Regex patterns for known sensitive value formats
_AADHAAR_RE = re.compile(r"\b(\d{4})\s?(\d{4})\s?(\d{4})\b")
_PAN_RE = re.compile(r"\b([A-Z]{5})(\d{4})([A-Z])\b")
_MOBILE_RE = re.compile(r"\b(\+?91)?(\d{5})(\d{5})\b")


# ──────────────────────────────────────────────────────────────────────────────
# Masking
# ──────────────────────────────────────────────────────────────────────────────

def mask_sensitive_value(field_key: str, value: Optional[str]) -> str:
    """Return a masked version of value safe for audit log storage.

    Rules (applied in order):
      1. If field_key matches a sensitive pattern → apply value-level masking.
      2. Apply regex masking for known PII formats regardless of key.
      3. Return original value if no sensitive pattern matched.

    Examples:
      mask_sensitive_value("aadhaar_number", "1234 5678 9012")
        → "XXXX XXXX 9012"
      mask_sensitive_value("full_name", "Ananya Sharma")
        → "Ananya Sharma"   (not sensitive)
      mask_sensitive_value("mobile_number", "9876543210")
        → "XXXXX43210"
    """
    if not value:
        return ""

    key_lower = field_key.lower()
    is_sensitive = any(pat in key_lower for pat in _SENSITIVE_FIELD_PATTERNS)

    masked = value

    # Aadhaar: keep last 4 digits
    masked = _AADHAAR_RE.sub(lambda m: f"XXXX XXXX {m.group(3)}", masked)

    # PAN: mask first 5 alpha chars
    masked = _PAN_RE.sub(lambda m: f"XXXXX{m.group(2)}{m.group(3)}", masked)

    # Mobile: mask first 5 digits
    masked = _MOBILE_RE.sub(
        lambda m: f"{m.group(1) or ''}XXXXX{m.group(3)}", masked
    )

    if is_sensitive and masked == value:
        # Generic sensitive field — mask all but last 4 chars
        if len(value) > 4:
            masked = "X" * (len(value) - 4) + value[-4:]
        else:
            masked = "XXXX"

    return masked


# ──────────────────────────────────────────────────────────────────────────────
# Screenshot capture
# ──────────────────────────────────────────────────────────────────────────────

async def safe_screenshot(
    page: Any,
    run_id: str,
    label: str,
    minio_client: Any,
    bucket: str = "submission-artifacts",
) -> Optional[str]:
    """Take a screenshot and upload it to MinIO.

    Args:
        page:         Playwright Page object.
        run_id:       SubmissionRun UUID (used in the MinIO object key).
        label:        Short label for this step (e.g. 'login', 'captcha', 'error').
        minio_client: An initialised MinIO / boto3 S3 client.
        bucket:       MinIO bucket name.

    Returns:
        MinIO object key string, or None if the screenshot failed.
    """
    try:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        key = f"submissions/{run_id}/{ts}_{label}.png"

        png_bytes: bytes = await page.screenshot(full_page=False)

        # Upload via MinIO put_object
        minio_client.put_object(
            Bucket=bucket,
            Key=key,
            Body=io.BytesIO(png_bytes),
            ContentType="image/png",
            ContentLength=len(png_bytes),
        )
        logger.debug("Screenshot saved: %s", key)
        return key

    except Exception as exc:  # noqa: BLE001
        logger.warning("Screenshot failed for run %s / label %s: %s", run_id, label, exc)
        return None


# ──────────────────────────────────────────────────────────────────────────────
# Navigation helpers
# ──────────────────────────────────────────────────────────────────────────────

async def wait_for_navigation(
    page: Any,
    expected_url_fragment: Optional[str] = None,
    timeout_ms: int = 15_000,
) -> bool:
    """Wait for a navigation to complete (optionally checking URL).

    Args:
        page:                   Playwright Page.
        expected_url_fragment:  If provided, also asserts the current URL
                                contains this fragment after navigation.
        timeout_ms:             Max wait in milliseconds.

    Returns:
        True if navigation succeeded (and URL matches if requested).
    """
    try:
        await page.wait_for_load_state("networkidle", timeout=timeout_ms)
        if expected_url_fragment:
            current_url = page.url
            if expected_url_fragment not in current_url:
                logger.warning(
                    "Navigation ended at %r — expected fragment %r not found.",
                    current_url,
                    expected_url_fragment,
                )
                return False
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("Navigation timeout/error: %s", exc)
        return False


async def wait_for_selector_safe(
    page: Any,
    selector: str,
    timeout_ms: int = 10_000,
) -> bool:
    """Wait for a DOM element to appear. Returns False (not raise) on timeout."""
    try:
        await page.wait_for_selector(selector, timeout=timeout_ms)
        return True
    except Exception:  # noqa: BLE001
        return False


# ──────────────────────────────────────────────────────────────────────────────
# Error detection
# ──────────────────────────────────────────────────────────────────────────────

async def detect_form_error(page: Any) -> Optional[str]:
    """Scan the page for common error banner patterns.

    Returns the error message text if found, None otherwise.
    Common selectors tried: .error, .alert-danger, [role=alert], .form-error
    """
    selectors = [
        ".error-message", ".alert-danger", ".alert-error",
        "[role='alert']", ".form-error", ".error-banner",
        "#error-message", ".validation-error",
    ]
    for selector in selectors:
        try:
            el = await page.query_selector(selector)
            if el:
                text = (await el.inner_text()).strip()
                if text:
                    return text
        except Exception:  # noqa: BLE001
            continue
    return None


def generate_run_artifact_prefix(run_id: str) -> str:
    """Return the MinIO prefix for all artifacts of a given run."""
    return f"submissions/{run_id}/"

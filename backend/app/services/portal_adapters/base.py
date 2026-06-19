"""Abstract base class for all portal adapters.

Every portal adapter must:
  1. Subclass PortalAdapter
  2. Set class-level adapter_id, display_name, portal_url
  3. Implement all abstract methods
  4. Call registry.register(cls) or use the @registry.adapter decorator

CAPTCHA policy (hardcoded, not configurable):
  handle_captcha() MUST return CaptchaAction.PAUSE_FOR_USER.
  Auto-solving CAPTCHAs is architecturally prohibited.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Result data classes
# ──────────────────────────────────────────────────────────────────────────────

class CaptchaAction(str, Enum):
    """The only valid response to a CAPTCHA — pause for human."""
    PAUSE_FOR_USER = "pause_for_user"


@dataclass
class FieldFillResult:
    field_id: str
    success: bool
    masked_value: Optional[str] = None
    error: Optional[str] = None


@dataclass
class UploadResult:
    slot_id: str
    success: bool
    filename: Optional[str] = None
    error: Optional[str] = None


@dataclass
class ValidationResult:
    passed: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class SubmissionResult:
    success: bool
    portal_reference: Optional[str] = None
    error: Optional[str] = None
    confirmation_screenshot_key: Optional[str] = None


# ──────────────────────────────────────────────────────────────────────────────
# Abstract adapter
# ──────────────────────────────────────────────────────────────────────────────

class PortalAdapter(ABC):
    """Abstract interface every portal adapter must implement.

    Attributes:
        adapter_id:          Unique snake_case identifier. Must be stable across
                             versions (used as FK-like reference in submission_runs).
        display_name:        Human-readable name shown in the UI.
        portal_url:          Base URL of the target portal.
        supported_form_types: List of form type labels this adapter handles.
    """

    adapter_id: str
    display_name: str
    portal_url: str
    supported_form_types: list[str] = []

    # ------------------------------------------------------------------
    # Lifecycle hooks
    # ------------------------------------------------------------------

    @abstractmethod
    async def login(self, page: Any, credentials: dict) -> bool:
        """Navigate to the login page and authenticate.

        Args:
            page: Playwright Page object.
            credentials: Dict containing portal-specific keys
                         (e.g. {"username": ..., "password": ...}).

        Returns:
            True if login succeeded and session is active.
        """

    @abstractmethod
    async def load_form(self, page: Any, form_url: str) -> bool:
        """Navigate to the application form and ensure it is ready to fill.

        Args:
            page: Playwright Page object (already logged in).
            form_url: The URL of the specific form to fill.

        Returns:
            True if the form page loaded successfully.
        """

    @abstractmethod
    async def fill_fields(
        self,
        page: Any,
        field_values: dict[str, str],
    ) -> list[FieldFillResult]:
        """Fill every form field with the corresponding value.

        Args:
            page: Playwright Page object.
            field_values: Mapping of form_field_id → plaintext value.
                          Values are decrypted by the caller; this method
                          must NOT log them verbatim.

        Returns:
            List of per-field results.
        """

    @abstractmethod
    async def upload_documents(
        self,
        page: Any,
        upload_slots: list[dict],
    ) -> list[UploadResult]:
        """Attach documents to the form's file-upload slots.

        Args:
            page: Playwright Page object.
            upload_slots: List of dicts:
                {slot_id, local_path, mime_type, expected_format, max_size_kb}

        Returns:
            List of per-slot results.
        """

    @abstractmethod
    async def validate(self, page: Any) -> ValidationResult:
        """Trigger the portal's built-in validation (e.g. click "Validate" / "Check").

        Returns:
            ValidationResult indicating whether the portal accepted the filled form.
        """

    @abstractmethod
    async def submit(self, page: Any) -> SubmissionResult:
        """Click the final submit button and capture the confirmation.

        This method must only be called after human approval has been
        recorded in SubmissionRun.approved_by.

        Returns:
            SubmissionResult with portal_reference if successful.
        """

    # ------------------------------------------------------------------
    # CAPTCHA handling — hardcoded policy, no override allowed
    # ------------------------------------------------------------------

    async def handle_captcha(self, page: Any) -> CaptchaAction:
        """Called when a CAPTCHA is detected anywhere in the submission flow.

        Policy: ALWAYS pause for human. Auto-solving is architecturally
        prohibited (see build spec § 13 / Phase 3 rules).

        Subclasses MUST NOT override this method to attempt auto-solving.

        Returns:
            CaptchaAction.PAUSE_FOR_USER (always)
        """
        logger.info(
            "[%s] CAPTCHA detected — pausing for human resolution.",
            self.__class__.adapter_id,
        )
        return CaptchaAction.PAUSE_FOR_USER

    # ------------------------------------------------------------------
    # CAPTCHA detection helper (subclasses should override if needed)
    # ------------------------------------------------------------------

    async def is_captcha_present(self, page: Any) -> bool:
        """Return True if the current page contains a CAPTCHA challenge.

        Default implementation checks for common CAPTCHA indicators.
        Subclasses may override to add portal-specific detection.
        """
        content = await page.content()
        captcha_markers = [
            "captcha", "recaptcha", "hcaptcha",
            "Are you human", "I'm not a robot",
            "verify you are human",
        ]
        lower_content = content.lower()
        return any(m.lower() in lower_content for m in captcha_markers)

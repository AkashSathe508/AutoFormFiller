"""Mock Portal Adapter — Phase 3 implementation.

Drives the self-hosted mock_portal application.
Validates the full Submission Engine lifecycle (login, filling, uploads,
CAPTCHA pause/resume, and confirmation).
"""

from __future__ import annotations

import logging
from typing import Any

from app.services.portal_adapters.base import (
    FieldFillResult,
    PortalAdapter,
    SubmissionResult,
    UploadResult,
    ValidationResult,
)
from app.services.portal_adapters.registry import registry
from app.services.portal_adapters.utils import detect_form_error, wait_for_navigation

logger = logging.getLogger(__name__)


@registry.adapter
class MockPortalAdapter(PortalAdapter):
    adapter_id = "mock_portal"
    display_name = "Mock Government Portal"
    portal_url = "http://mock-portal:8080"
    supported_form_types = ["scholarship", "demo"]

    async def login(self, page: Any, credentials: dict) -> bool:
        await page.goto(f"{self.portal_url}/login")
        await page.fill("input[name='username']", credentials.get("username", ""))
        await page.fill("input[name='password']", credentials.get("password", ""))

        # Click login and wait for the apply page
        async with page.expect_navigation():
            await page.click("button#btn-login")

        error = await detect_form_error(page)
        if error or "/login" in page.url:
            logger.warning("Mock login failed: %s", error)
            return False
        return True

    async def load_form(self, page: Any, form_url: str) -> bool:
        # Since we just logged in, we should already be at /apply.
        # But if a specific form URL was passed, navigate there.
        target = form_url if form_url else f"{self.portal_url}/apply"
        if page.url != target:
            await page.goto(target)
            await wait_for_navigation(page)

        # Ensure the form rendered
        return await page.is_visible("form")

    async def fill_fields(
        self, page: Any, field_values: dict[str, str]
    ) -> list[FieldFillResult]:
        results = []

        # The mock portal has 3 specific fields we know about.
        # In a real adapter, this mapping is driven by form schema.
        for field_id, value in field_values.items():
            try:
                # Try locating by name attribute or id matching the canonical key
                selector = f"input[name='{field_id}'], input#{field_id}"
                if await page.is_visible(selector):
                    await page.fill(selector, value)
                    results.append(
                        FieldFillResult(field_id=field_id, success=True, masked_value=value)
                    )
                else:
                    results.append(
                        FieldFillResult(
                            field_id=field_id,
                            success=False,
                            error=f"Selector not found: {selector}",
                        )
                    )
            except Exception as exc:  # noqa: BLE001
                results.append(
                    FieldFillResult(field_id=field_id, success=False, error=str(exc))
                )

        # Move to next page
        async with page.expect_navigation():
            await page.click("button#btn-next")

        return results

    async def upload_documents(
        self, page: Any, upload_slots: list[dict]
    ) -> list[UploadResult]:
        results = []

        # We assume upload_slots has mappings for 'photo' and 'aadhaar_doc'
        for slot in upload_slots:
            slot_id = slot.get("slot_id")
            local_path = slot.get("local_path")
            if not local_path:
                continue

            try:
                selector = f"input[type='file'][name='{slot_id}']"
                if await page.is_visible(selector):
                    await page.set_input_files(selector, local_path)
                    results.append(
                        UploadResult(
                            slot_id=slot_id, success=True, filename=local_path.split("/")[-1]
                        )
                    )
                else:
                    results.append(
                        UploadResult(
                            slot_id=slot_id, success=False, error="File input not found."
                        )
                    )
            except Exception as exc:  # noqa: BLE001
                results.append(
                    UploadResult(slot_id=slot_id, success=False, error=str(exc))
                )

        # Move to next page (captcha)
        async with page.expect_navigation():
            await page.click("button#btn-upload")

        return results

    async def validate(self, page: Any) -> ValidationResult:
        # The mock portal doesn't have a distinct "validate" step before submit.
        # If we reached the confirm page successfully, validation passed.
        error = await detect_form_error(page)
        if error:
            return ValidationResult(passed=False, errors=[error])
        return ValidationResult(passed=True)

    async def submit(self, page: Any) -> SubmissionResult:
        # Check the agreement box on the confirm page
        try:
            await page.check("input#agree_terms")
            async with page.expect_navigation():
                await page.click("button#btn-final-submit")
        except Exception as exc:  # noqa: BLE001
            return SubmissionResult(success=False, error=str(exc))

        # We should now be on the success page. Extract the reference number.
        if "/apply/success" not in page.url:
            error = await detect_form_error(page)
            return SubmissionResult(
                success=False, error=error or "Final submission did not reach success page."
            )

        ref_element = await page.query_selector("#reference-number")
        if ref_element:
            ref = await ref_element.inner_text()
            return SubmissionResult(success=True, portal_reference=ref.strip())

        return SubmissionResult(
            success=False, error="Success page loaded, but reference number not found."
        )

    # ------------------------------------------------------------------
    # CAPTCHA detection
    # ------------------------------------------------------------------

    async def is_captcha_present(self, page: Any) -> bool:
        """The mock portal CAPTCHA page is at /apply/captcha."""
        if "/apply/captcha" in page.url:
            return True
        return await super().is_captcha_present(page)

    # Note: handle_captcha() is intentionally NOT overridden.
    # The base class method is used to enforce the PAUSE_FOR_USER policy.

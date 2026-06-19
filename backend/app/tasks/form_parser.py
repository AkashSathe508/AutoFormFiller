"""Form schema parsing Celery tasks.

Two entry points:
  1. parse_form_schema(template_id, url)     — web URL via Playwright (existing)
  2. parse_pdf_form(template_id, pdf_b64)    — PDF upload via Form Understanding Agent

Both write their results to the FormTemplate row identified by template_id.
"""

import base64
import json
import logging
from typing import List, Optional

from app.celery_app import celery_app
from app.core.config import settings

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Task 1: Web URL form parser (Playwright)
# ──────────────────────────────────────────────────────────────────────────────

@celery_app.task(
    bind=True,
    name="app.tasks.form_parser.parse_form_schema",
    max_retries=2,
    default_retry_delay=60,
    queue="parsing",
)
def parse_form_schema(self, template_id: str, url: str) -> dict:
    """Parse a government form URL and extract its field schema via Playwright.

    Args:
        template_id: UUID of the FormTemplate to update.
        url: URL of the government form to scrape.

    Returns:
        dict with field_count and upload_slots_count.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(settings.DATABASE_SYNC_URL)
    Session = sessionmaker(bind=engine)

    try:
        raw_fields = _scrape_form_fields(url)
        normalized_fields = _normalize_fields_with_llm(raw_fields, url)
        upload_slots = [f for f in normalized_fields if f.get("field_type") == "file"]
        form_fields = [f for f in normalized_fields if f.get("field_type") != "file"]

        with Session() as db:
            from app.models.form import FormTemplate
            from datetime import datetime, timezone

            template = db.query(FormTemplate).filter(FormTemplate.id == template_id).first()
            if not template:
                logger.error("FormTemplate %s not found", template_id)
                return {"error": "template_not_found"}

            template.field_schema = form_fields
            template.upload_slots = upload_slots
            template.last_validated_at = datetime.now(timezone.utc)
            db.commit()

        logger.info(
            "Web parse complete for %s: %d fields, %d upload slots",
            url, len(form_fields), len(upload_slots),
        )
        return {"field_count": len(form_fields), "upload_slots_count": len(upload_slots)}

    except Exception as exc:
        logger.exception("Form parsing failed for %s: %s", url, exc)
        raise self.retry(exc=exc)


# ──────────────────────────────────────────────────────────────────────────────
# Task 2: PDF form parser (Form Understanding Agent)
# ──────────────────────────────────────────────────────────────────────────────

@celery_app.task(
    bind=True,
    name="app.tasks.form_parser.parse_pdf_form",
    max_retries=2,
    default_retry_delay=60,
    queue="parsing",
)
def parse_pdf_form(self, template_id: str, pdf_b64: str, filename: str = "form.pdf") -> dict:
    """Parse a PDF form and extract its field schema.

    Args:
        template_id: UUID of the FormTemplate to update.
        pdf_b64:     Base64-encoded PDF bytes.
        filename:    Original upload filename (used for title extraction).

    Returns:
        dict with field_count, upload_slots_count, and parse_method.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(settings.DATABASE_SYNC_URL)
    Session = sessionmaker(bind=engine)

    try:
        pdf_bytes = base64.b64decode(pdf_b64)

        from ai_services.form_understanding_agent.pdf_parser import parse_pdf
        result = parse_pdf(
            pdf_bytes=pdf_bytes,
            filename=filename,
            ollama_host=settings.OLLAMA_HOST,
            ollama_model=settings.OLLAMA_PRIMARY_MODEL,
            ollama_timeout=settings.OLLAMA_TIMEOUT_SECONDS,
        )

        with Session() as db:
            from app.models.form import FormTemplate
            from datetime import datetime, timezone

            template = db.query(FormTemplate).filter(FormTemplate.id == template_id).first()
            if not template:
                logger.error("FormTemplate %s not found", template_id)
                return {"error": "template_not_found"}

            template.field_schema = result["fields"]
            template.upload_slots = result["upload_slots"]
            template.last_validated_at = datetime.now(timezone.utc)
            db.commit()

        logger.info(
            "PDF parse complete for template %s: %d fields, %d upload slots (method=%s)",
            template_id, len(result["fields"]), len(result["upload_slots"]),
            result.get("parse_method", "unknown"),
        )
        return {
            "field_count": len(result["fields"]),
            "upload_slots_count": len(result["upload_slots"]),
            "parse_method": result.get("parse_method"),
        }

    except Exception as exc:
        logger.exception("PDF form parsing failed for template %s: %s", template_id, exc)
        raise self.retry(exc=exc)


# ──────────────────────────────────────────────────────────────────────────────
# Helpers — Web scraping
# ──────────────────────────────────────────────────────────────────────────────

def _scrape_form_fields(url: str) -> List[dict]:
    """Use Playwright to scrape form fields from a government form URL."""
    from playwright.sync_api import sync_playwright

    fields = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (compatible; AutoFormFiller/1.0; +https://autoformfiller.in)",
            locale="en-IN",
        )
        page = context.new_page()

        try:
            page.goto(url, timeout=30000, wait_until="networkidle")
            page.wait_for_timeout(2000)  # Wait for JS rendering

            fields = page.evaluate("""() => {
                const fields = [];
                const inputs = document.querySelectorAll('input, select, textarea');

                inputs.forEach(el => {
                    if (el.type === 'hidden' || el.type === 'submit' || el.type === 'button') return;

                    const id = el.id || el.name || '';
                    if (!id) return;

                    // Find associated label
                    let label = '';
                    const labelEl = document.querySelector(`label[for="${id}"]`);
                    if (labelEl) {
                        label = labelEl.textContent.trim();
                    } else {
                        const parentLabel = el.closest('label');
                        if (parentLabel) label = parentLabel.textContent.trim();
                    }

                    // Aria-label fallback
                    if (!label) label = el.getAttribute('aria-label') || el.placeholder || id;

                    // Options for select
                    const options = [];
                    if (el.tagName === 'SELECT') {
                        el.querySelectorAll('option').forEach(opt => {
                            if (opt.value) options.push(opt.text.trim());
                        });
                    }

                    fields.push({
                        field_id: id,
                        label: label,
                        field_type: el.type || el.tagName.toLowerCase(),
                        required: el.required || false,
                        max_length: el.maxLength > 0 ? el.maxLength : null,
                        options: options.length > 0 ? options : null,
                        placeholder: el.placeholder || null,
                        read_only: el.readOnly || false,
                    });
                });

                return fields;
            }""")

        except Exception as e:
            logger.warning("Playwright scrape error for %s: %s", url, e)
        finally:
            browser.close()

    return fields


def _normalize_fields_with_llm(raw_fields: List[dict], url: str) -> List[dict]:
    """Use Ollama LLM to normalize and classify scraped form fields."""
    import httpx

    if not raw_fields:
        return []

    fields_json = json.dumps(raw_fields[:50], ensure_ascii=False)

    prompt = f"""You are an expert at analysing Indian government online forms.

Below is a list of form fields scraped from: {url}

For each field, return a normalized JSON array. Each object must have:
- field_id: original id/name
- label: human-readable label (translate from Hindi/regional if needed)
- field_type: one of [text, number, date, select, checkbox, radio, file, email, tel, textarea, signature]
- required: true/false
- options: list of options for select/radio, null otherwise
- max_length: max character length or null
- read_only: true/false
- profile_field_hint: best matching profile field key from this list:
  [full_name, dob, gender, father_name, mother_name, spouse_name,
   aadhaar_number, pan_number, passport_number, driving_license_number,
   voter_id, email, mobile_number, address_line1, address_line2,
   city, district, state, pincode, country, bank_account_number, bank_ifsc,
   annual_income, caste, religion, nationality, category, photograph, signature,
   class_10_percentage, class_12_percentage, graduation_percentage]
  Use null if no clear match.

Raw fields:
{fields_json}

Respond with ONLY a valid JSON array, no explanation:"""

    try:
        response = httpx.post(
            f"{settings.OLLAMA_HOST}/api/generate",
            json={
                "model": settings.OLLAMA_PRIMARY_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.1},
            },
            timeout=settings.OLLAMA_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        raw = response.json().get("response", "[]").strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
        return json.loads(raw)
    except Exception as e:
        logger.warning("LLM field normalization failed: %s. Returning raw fields.", e)
        return raw_fields

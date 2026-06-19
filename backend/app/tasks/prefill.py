"""Form pre-fill Celery task — Phase 2.

Pipeline:
  1. Load FormInstance + FormTemplate field_schema
  2. Load all ProfileField records for the profile, building a
     field_key → (ProfileField, decrypted_dek) map.
  3. For each form field, resolve the best profile field via
     FormMappingService (rule → embedding → LLM, with FieldMappingCache).
  4. Decrypt the matched profile field value using the document's DEK,
     then re-encrypt it with the profile's primary DEK for storage in
     form_field_values. This avoids generating a phantom instance_dek
     that was never persisted (the previous bug).
  5. Flag fields needing human attention:
       - mapped via LLM (lowest confidence)
       - required but unmapped
       - decryption errors
  6. Update FormInstance status → 'needs_review' or 'ready'.
  7. Return fill statistics including unmapped_fields list.
"""

import logging
from typing import Dict, List, Optional, Tuple

from app.celery_app import celery_app
from app.core.config import settings

logger = logging.getLogger(__name__)

# Confidence threshold below which a mapping is flagged for human review
REVIEW_CONFIDENCE_THRESHOLD = 0.75


@celery_app.task(
    bind=True,
    name="app.tasks.prefill.prefill_form_instance",
    max_retries=2,
    default_retry_delay=30,
    queue="prefill",
)
def prefill_form_instance(self, instance_id: str) -> dict:
    """Pre-fill a FormInstance with profile data.

    Args:
        instance_id: UUID of the FormInstance to fill.

    Returns:
        dict with fill statistics.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(settings.DATABASE_SYNC_URL)
    Session = sessionmaker(bind=engine)

    try:
        with Session() as db:
            from app.models.form import FormInstance, FormTemplate, FormFieldValue
            from app.models.profile_field import ProfileField
            from app.core.encryption import unwrap_dek, decrypt_field, encrypt_field

            # ── 1. Load form instance and template ───────────────────────
            instance = db.query(FormInstance).filter(FormInstance.id == instance_id).first()
            if not instance:
                logger.error("FormInstance %s not found", instance_id)
                return {"error": "instance_not_found"}

            template = db.query(FormTemplate).filter(
                FormTemplate.id == instance.form_template_id
            ).first()
            if not template or not template.field_schema:
                logger.warning(
                    "No field schema for template %s — marking needs_review",
                    instance.form_template_id,
                )
                _set_status(instance, "needs_review")
                db.commit()
                return {"filled": 0, "attention": 0, "unmapped": []}

            # ── 2. Build profile field map ────────────────────────────────
            # field_key → (ProfileField, dek_bytes | None)
            profile_fields = (
                db.query(ProfileField)
                .filter(ProfileField.profile_id == instance.profile_id)
                .all()
            )

            profile_field_map: Dict[str, Tuple] = {}
            primary_dek: Optional[bytes] = None  # DEK from the first resolved document

            for pf in profile_fields:
                dek = _resolve_dek(db, pf)
                profile_field_map[pf.field_key] = (pf, dek)
                if dek and primary_dek is None:
                    primary_dek = dek  # Use first available DEK for re-encryption

            if not profile_field_map:
                logger.warning("Profile %s has no fields — marking needs_review", instance.profile_id)
                _set_status(instance, "needs_review")
                db.commit()
                return {"filled": 0, "attention": 0, "unmapped": []}

            # ── 3. Delete any stale field values from prior runs ──────────
            db.query(FormFieldValue).filter(
                FormFieldValue.form_instance_id == instance_id
            ).delete(synchronize_session=False)

            # ── 4. Initialise mapping service ─────────────────────────────
            from app.services.form_mapping_service import FormMappingService

            mapper = FormMappingService(
                db=db,
                template_id=str(instance.form_template_id),
                profile_field_keys=list(profile_field_map.keys()),
                embedding_model_name=settings.EMBEDDING_MODEL,
                embedding_threshold=settings.EMBEDDING_COSINE_THRESHOLD,
                ollama_host=settings.OLLAMA_HOST,
                ollama_model=settings.OLLAMA_PRIMARY_MODEL,
                ollama_timeout=settings.OLLAMA_TIMEOUT_SECONDS,
            )

            # ── 5. Per-field mapping + value fill ─────────────────────────
            filled_count = 0
            attention_count = 0
            unmapped_fields: List[dict] = []

            for form_field in template.field_schema:
                fid = str(form_field.get("field_id", ""))
                if not fid:
                    continue

                profile_hint = form_field.get("profile_field_hint")

                matched_key, confidence, method = mapper.resolve(form_field, profile_hint)

                value_encrypted: Optional[str] = None
                needs_attention = False
                attention_reason: Optional[str] = None

                if matched_key and matched_key in profile_field_map:
                    pf, dek = profile_field_map[matched_key]
                    try:
                        if dek:
                            plain = decrypt_field(pf.field_value_encrypted, dek, matched_key)
                        else:
                            # Stored without encryption (dev mode / pre-encryption data)
                            plain = pf.field_value_encrypted

                        # Re-encrypt using primary DEK so all form fields share a
                        # consistent, retrievable key (stored in the profile, not ephemeral)
                        if primary_dek:
                            value_encrypted = encrypt_field(plain, primary_dek, fid)
                        else:
                            value_encrypted = plain  # dev fallback

                        filled_count += 1

                        # Flag LLM-mapped or low-confidence fields for human review
                        if method == "llm" or confidence < REVIEW_CONFIDENCE_THRESHOLD:
                            needs_attention = True
                            attention_reason = (
                                f"Low confidence mapping ({method}, {confidence:.2f})"
                            )
                            attention_count += 1

                    except Exception as e:
                        logger.warning("Decrypt error for field %s: %s", matched_key, e)
                        needs_attention = True
                        attention_reason = "Decryption error — please enter manually"
                        attention_count += 1
                else:
                    # No mapping found
                    if form_field.get("required"):
                        needs_attention = True
                        attention_reason = "Required field not found in profile"
                        attention_count += 1

                    unmapped_fields.append({
                        "field_id": fid,
                        "label": form_field.get("label", fid),
                        "required": form_field.get("required", False),
                        "reason": attention_reason or "No profile field match found",
                    })

                fv = FormFieldValue(
                    form_instance_id=instance_id,
                    form_field_id=fid,
                    value_encrypted=value_encrypted,
                    method=method,
                    source_field_key=matched_key,
                    confidence=confidence,
                    needs_attention=needs_attention,
                    attention_reason=attention_reason,
                )
                db.add(fv)

            # ── 6. Update instance status ──────────────────────────────────
            new_status = "needs_review" if attention_count > 0 else "ready"
            _set_status(instance, new_status)
            db.commit()

            logger.info(
                "Pre-fill complete [%s]: %d filled, %d attention, %d unmapped → %s",
                instance_id[:8], filled_count, attention_count, len(unmapped_fields), new_status,
            )
            return {
                "filled": filled_count,
                "attention": attention_count,
                "unmapped": unmapped_fields,
                "status": new_status,
            }

    except Exception as exc:
        logger.exception("Pre-fill task failed for instance %s: %s", instance_id, exc)
        raise self.retry(exc=exc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_dek(db, profile_field) -> Optional[bytes]:
    """Unwrap the DEK for a ProfileField's source document.

    Returns unwrapped DEK bytes, or None if the document has no encryption key.
    Never swallows errors silently — logs and returns None so the caller can
    decide whether to flag the field for manual entry.
    """
    if not profile_field.source_document_id:
        return None
    try:
        from app.models.document import Document
        from app.core.encryption import unwrap_dek

        doc = db.query(Document).filter(
            Document.id == profile_field.source_document_id
        ).first()
        if not doc or not doc.encryption_key_id:
            return None
        return unwrap_dek(doc.encryption_key_id)
    except Exception as e:
        logger.warning(
            "Could not unwrap DEK for document %s: %s",
            profile_field.source_document_id, e,
        )
        return None


def _set_status(instance, status: str) -> None:
    """Update FormInstance.status in-place."""
    instance.status = status

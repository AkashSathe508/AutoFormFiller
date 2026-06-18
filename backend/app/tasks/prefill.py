"""Form pre-fill Celery task.

Pipeline:
  1. Load FormInstance + FormTemplate field_schema
  2. Load all ProfileField records for the profile
  3. For each form field:
     a. Try exact field_key match (from FieldMappingCache or profile_field_hint)
     b. If no match, use embedding cosine similarity (pgvector)
     c. If similarity < threshold, ask LLM for mapping
  4. Decrypt matched profile field value, re-encrypt for FormFieldValue
  5. Flag fields that need human attention
  6. Update FormInstance status to 'needs_review' or 'ready'
"""

import json
import logging
from typing import Optional

from app.celery_app import celery_app
from app.core.config import settings

logger = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    name="app.tasks.prefill.prefill_form_instance",
    max_retries=2,
    default_retry_delay=30,
    queue="prefill",
)
def prefill_form_instance(self, instance_id: str) -> dict:
    """
    Pre-fill a FormInstance with profile data.

    Args:
        instance_id: UUID of the FormInstance to fill

    Returns:
        dict with fill statistics
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(settings.DATABASE_SYNC_URL)
    Session = sessionmaker(bind=engine)

    try:
        with Session() as db:
            from app.models.form import FormInstance, FormTemplate, FormFieldValue, FieldMappingCache
            from app.models.profile_field import ProfileField
            from app.core.encryption import unwrap_dek, decrypt_field, encrypt_field, generate_dek, wrap_dek

            # ── 1. Load form instance and template ───────────────────────
            instance = db.query(FormInstance).filter(FormInstance.id == instance_id).first()
            if not instance:
                logger.error(f"FormInstance {instance_id} not found")
                return {"error": "instance_not_found"}

            template = db.query(FormTemplate).filter(FormTemplate.id == instance.form_template_id).first()
            if not template or not template.field_schema:
                logger.warning(f"No field schema for template {instance.form_template_id}")
                _update_instance_status(db, instance, "needs_review")
                return {"filled": 0, "attention": 0}

            # ── 2. Load profile fields (encrypted) ───────────────────────
            profile_fields = (
                db.query(ProfileField)
                .filter(ProfileField.profile_id == instance.profile_id)
                .all()
            )
            # Build lookup: field_key → (ProfileField, dek)
            profile_field_map = {}
            for pf in profile_fields:
                try:
                    dek = unwrap_dek(pf.source_document_id and _get_doc_dek(db, str(pf.source_document_id)) or b"")
                except Exception:
                    dek = None
                profile_field_map[pf.field_key] = (pf, dek)

            # ── 3. Per-form-field mapping ─────────────────────────────────
            filled_count = 0
            attention_count = 0
            instance_dek = generate_dek()

            for form_field in template.field_schema:
                fid = form_field.get("field_id", "")
                profile_hint = form_field.get("profile_field_hint")

                matched_key, confidence, method = _resolve_field_mapping(
                    db, template, form_field, profile_field_map, profile_hint
                )

                value_encrypted = None
                needs_attention = False
                attention_reason = None

                if matched_key and matched_key in profile_field_map:
                    pf, dek = profile_field_map[matched_key]
                    try:
                        if dek:
                            plain = decrypt_field(pf.field_value_encrypted, dek, matched_key)
                        else:
                            plain = pf.field_value_encrypted  # Stored as plain in dev
                        value_encrypted = encrypt_field(plain, instance_dek, fid)
                        filled_count += 1
                    except Exception as e:
                        logger.warning(f"Failed to decrypt field {matched_key}: {e}")
                        needs_attention = True
                        attention_reason = "Decryption error"
                        attention_count += 1
                else:
                    if form_field.get("required"):
                        needs_attention = True
                        attention_reason = "Required field not found in profile"
                        attention_count += 1

                fv = FormFieldValue(
                    form_instance_id=instance_id,
                    form_field_id=fid,
                    value_encrypted=value_encrypted,
                    method=method,
                    needs_attention=needs_attention,
                    attention_reason=attention_reason,
                )
                db.add(fv)

                # Cache the mapping for future use
                if matched_key and confidence > 0:
                    cache_entry = FieldMappingCache(
                        form_template_id=str(template.id),
                        form_field_id=fid,
                        profile_field_key=matched_key,
                        confidence=confidence,
                        method=method,
                    )
                    db.add(cache_entry)

            # ── 4. Update instance status ─────────────────────────────────
            new_status = "needs_review" if attention_count > 0 else "ready"
            _update_instance_status(db, instance, new_status)
            db.commit()

            logger.info(
                f"Pre-fill complete for instance {instance_id}: "
                f"{filled_count} filled, {attention_count} need attention"
            )
            return {"filled": filled_count, "attention": attention_count}

    except Exception as exc:
        logger.exception(f"Pre-fill task failed for instance {instance_id}: {exc}")
        raise self.retry(exc=exc)


def _get_doc_dek(db, document_id: str) -> bytes:
    """Fetch and unwrap DEK for a document."""
    from app.models.document import Document
    from app.core.encryption import unwrap_dek

    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise ValueError(f"Document {document_id} not found")
    return unwrap_dek(doc.encryption_key_id)


def _resolve_field_mapping(
    db, template, form_field: dict, profile_field_map: dict, profile_hint: Optional[str]
) -> tuple[Optional[str], float, str]:
    """
    Resolve which profile_field_key matches a form field.

    Priority:
    1. FieldMappingCache (cached from previous fills)
    2. profile_field_hint from LLM normalization (high confidence)
    3. Embedding cosine similarity via pgvector
    4. Ollama LLM fallback
    """
    fid = form_field.get("field_id", "")

    # Check mapping cache
    from app.models.form import FieldMappingCache
    cached = (
        db.query(FieldMappingCache)
        .filter(
            FieldMappingCache.form_template_id == str(template.id),
            FieldMappingCache.form_field_id == fid,
        )
        .order_by(FieldMappingCache.confidence.desc())
        .first()
    )
    if cached and cached.profile_field_key:
        return cached.profile_field_key, cached.confidence, "cache"

    # Use LLM hint if it matches a known profile field
    if profile_hint and profile_hint in profile_field_map:
        return profile_hint, 0.95, "hint"

    # Embedding similarity
    matched_key, sim_score = _embedding_match(form_field, list(profile_field_map.keys()))
    if matched_key and sim_score >= settings.EMBEDDING_COSINE_THRESHOLD:
        return matched_key, sim_score, "embedding"

    # LLM fallback
    llm_key = _llm_match(form_field, list(profile_field_map.keys()))
    if llm_key:
        return llm_key, 0.70, "llm"

    return None, 0.0, "none"


def _embedding_match(form_field: dict, profile_keys: list) -> tuple[Optional[str], float]:
    """Find best matching profile key using sentence embeddings."""
    try:
        from sentence_transformers import SentenceTransformer
        import numpy as np

        label = form_field.get("label", form_field.get("field_id", ""))
        model = SentenceTransformer(settings.EMBEDDING_MODEL)
        query_emb = model.encode(f"query: {label}", normalize_embeddings=True)

        best_key = None
        best_score = 0.0
        for key in profile_keys:
            key_emb = model.encode(f"passage: {key.replace('_', ' ')}", normalize_embeddings=True)
            score = float(np.dot(query_emb, key_emb))
            if score > best_score:
                best_score = score
                best_key = key

        return best_key, best_score
    except Exception as e:
        logger.warning(f"Embedding match failed: {e}")
        return None, 0.0


def _llm_match(form_field: dict, profile_keys: list) -> Optional[str]:
    """Use Ollama LLM to identify the best profile field match."""
    import httpx

    label = form_field.get("label", form_field.get("field_id", ""))
    keys_str = ", ".join(profile_keys[:30])

    prompt = f"""Match this government form field to the most appropriate profile key.

Form field label: "{label}"
Form field type: {form_field.get("field_type", "text")}

Available profile keys: {keys_str}

Respond with ONLY the profile key name, or "none" if there is no good match:"""

    try:
        response = httpx.post(
            f"{settings.OLLAMA_HOST}/api/generate",
            json={
                "model": settings.OLLAMA_PRIMARY_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.0},
            },
            timeout=30,
        )
        response.raise_for_status()
        matched = response.json().get("response", "none").strip().lower()
        if matched == "none" or matched not in profile_keys:
            return None
        return matched
    except Exception as e:
        logger.warning(f"LLM match failed: {e}")
        return None


def _update_instance_status(db, instance, new_status: str) -> None:
    """Update FormInstance status."""
    instance.status = new_status

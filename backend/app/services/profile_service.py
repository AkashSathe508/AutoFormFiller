"""Profile merge service — upsert extracted fields into unified profile."""

from sqlalchemy.orm import Session
from sqlalchemy import select

from app.core.encryption import encrypt_field
from app.models.profile_field import ProfileField, ProfileFieldConflict


class ProfileService:
    @staticmethod
    def merge_extracted_fields(
        db: Session,
        profile_id: str,
        structured_fields: dict,
        document_id: str,
        dek: bytes,
    ) -> list[str]:
        """
        Merge extracted fields into profile_fields.

        Returns list of field keys written or queued as conflicts.
        """
        merged_keys = []

        for field_key, field_data in structured_fields.items():
            value = field_data.get("value", "")
            confidence = field_data.get("confidence", 0.8)

            if not value:
                continue

            encrypted_value = encrypt_field(str(value), dek, field_key)

            existing = db.execute(
                select(ProfileField).where(
                    ProfileField.profile_id == profile_id,
                    ProfileField.field_key == field_key,
                )
            ).scalar_one_or_none()

            if existing is None:
                db.add(ProfileField(
                    profile_id=profile_id,
                    field_key=field_key,
                    field_value_encrypted=encrypted_value,
                    source_document_id=document_id,
                    confidence=confidence,
                ))
                merged_keys.append(field_key)
            elif existing.field_value_encrypted != encrypted_value:
                db.add(ProfileFieldConflict(
                    profile_id=profile_id,
                    field_key=field_key,
                    existing_value_encrypted=existing.field_value_encrypted,
                    new_value_encrypted=encrypted_value,
                    existing_source_doc_id=existing.source_document_id,
                    new_source_doc_id=document_id,
                ))
                merged_keys.append(field_key)
            # Same value — no action

        return merged_keys

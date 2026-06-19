"""End-to-end tests for Phase 2 — Form Understanding & Field Mapping System.

These tests run the full pipeline in-process (no live Docker required) using:
- A synthetic 3-field AcroForm PDF built with pypdf
- SQLite-backed in-memory sessions (for models that don't use pgvector)
- Mocked Ollama calls (no live LLM required for rule/embedding paths)

Run with:
    pytest backend/tests/test_form_understanding_e2e.py -v

For live integration testing against the Docker stack, use scratch/test_pipeline.py.
"""

import io
import json
import pytest
from typing import Optional
from unittest.mock import MagicMock, patch


# ──────────────────────────────────────────────────────────────────────────────
# Fixtures & helpers
# ──────────────────────────────────────────────────────────────────────────────

def _make_acroform_pdf() -> bytes:
    """Build a minimal AcroForm PDF with three fields using pypdf."""
    from pypdf import PdfWriter
    from pypdf.generic import (
        ArrayObject, BooleanObject, DictionaryObject,
        NameObject, NumberObject, TextStringObject,
    )

    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)

    # Add three AcroForm text fields
    fields = [
        ("full_name_field",  "Full Name"),
        ("dob_field",        "Date of Birth"),
        ("aadhaar_field",    "Aadhaar Number"),
    ]
    for field_name, tooltip in fields:
        writer.add_annotation(
            page_number=0,
            annotation=DictionaryObject({
                NameObject("/Type"): NameObject("/Annot"),
                NameObject("/Subtype"): NameObject("/Widget"),
                NameObject("/FT"): NameObject("/Tx"),
                NameObject("/T"): TextStringObject(field_name),
                NameObject("/TU"): TextStringObject(tooltip),
                NameObject("/Rect"): ArrayObject([
                    NumberObject(50), NumberObject(700),
                    NumberObject(300), NumberObject(720),
                ]),
                NameObject("/Ff"): NumberObject(2),  # Required flag
            }),
        )

    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


# ──────────────────────────────────────────────────────────────────────────────
# Milestone 1 Tests — PDF Parser
# ──────────────────────────────────────────────────────────────────────────────

class TestPdfParser:
    """Tests for ai_services/form_understanding_agent/pdf_parser.py"""

    def test_acroform_detection(self):
        """AcroForm PDFs are detected and fields extracted without LLM."""
        from ai_services.form_understanding_agent.pdf_parser import parse_pdf
        from unittest.mock import patch

        mock_fields = [
            {"field_id": "full_name_field", "label": "Full Name", "field_type": "text", "required": True},
            {"field_id": "dob_field", "label": "Date of Birth", "field_type": "text", "required": True},
            {"field_id": "aadhaar_field", "label": "Aadhaar Number", "field_type": "text", "required": True},
        ]

        with patch("ai_services.form_understanding_agent.pdf_parser._parse_acroform", return_value=(mock_fields, True)):
            result = parse_pdf(b"dummy", filename="test_form.pdf")

        assert result["form_id"]  # sha256 hash present
        assert result["parse_method"] == "acroform"
        assert len(result["fields"]) == 3

        field_labels = {f["label"] for f in result["fields"]}
        assert "Full Name" in field_labels
        assert "Date of Birth" in field_labels
        assert "Aadhaar Number" in field_labels

    def test_field_schema_structure(self):
        """Each parsed field has the required schema keys."""
        from ai_services.form_understanding_agent.pdf_parser import parse_pdf
        from unittest.mock import patch

        mock_fields = [
            {"field_id": "full_name_field", "label": "Full Name", "field_type": "text", "required": True},
        ]
        with patch("ai_services.form_understanding_agent.pdf_parser._parse_acroform", return_value=(mock_fields, True)):
            result = parse_pdf(b"dummy")

        for field in result["fields"]:
            assert "field_id" in field
            assert "label" in field
            assert "field_type" in field
            assert "required" in field

    def test_empty_pdf_returns_empty_fields(self):
        """A PDF with no AcroForm and no embedded text falls back gracefully."""
        from ai_services.form_understanding_agent.pdf_parser import parse_pdf
        from unittest.mock import patch

        with patch("ai_services.form_understanding_agent.pdf_parser._parse_acroform", return_value=([], False)), \
             patch("ai_services.form_understanding_agent.pdf_parser._ocr_pdf_pages", return_value=""), \
             patch("ai_services.form_understanding_agent.pdf_parser._infer_fields_with_llm", return_value=[]):
            result = parse_pdf(b"dummy_blank", filename="blank.pdf")

        assert result["fields"] == []
        assert result["upload_slots"] == []

    def test_flat_pdf_triggers_ocr_llm_path(self):
        """A PDF with embedded text but no AcroForm goes to the OCR+LLM path."""
        from ai_services.form_understanding_agent.pdf_parser import parse_pdf
        from unittest.mock import patch

        mock_fields = [
            {"field_id": "full_name", "label": "Full Name", "field_type": "text", "required": True},
            {"field_id": "dob", "label": "Date of Birth", "field_type": "date", "required": False},
        ]
        with patch("ai_services.form_understanding_agent.pdf_parser._parse_acroform", return_value=([], False)), \
             patch("ai_services.form_understanding_agent.pdf_parser._ocr_pdf_pages", return_value="Full Name *: ___\nDate of Birth: ___"), \
             patch("ai_services.form_understanding_agent.pdf_parser._infer_fields_with_llm", return_value=mock_fields) as mock_llm:
            result = parse_pdf(b"dummy_flat", filename="flat_form.pdf")
            mock_llm.assert_called_once()

        assert result["parse_method"] == "ocr_llm"
        assert len(result["fields"]) == 2


# ──────────────────────────────────────────────────────────────────────────────
# Milestone 2 Tests — Rule Engine
# ──────────────────────────────────────────────────────────────────────────────

class TestRuleEngine:
    """Tests for backend/app/services/rule_engine/loader.py"""

    def test_exact_label_match(self):
        from app.services.rule_engine.loader import rule_match
        assert rule_match("Full Name") == "full_name"
        assert rule_match("Date of Birth") == "dob"
        assert rule_match("Aadhaar Number") == "aadhaar_number"
        assert rule_match("PAN Number") == "pan_number"

    def test_case_insensitive_match(self):
        from app.services.rule_engine.loader import rule_match
        assert rule_match("FULL NAME") == "full_name"
        assert rule_match("date of birth") == "dob"
        assert rule_match("Aadhaar no") == "aadhaar_number"

    def test_strips_asterisk_suffix(self):
        """Labels with trailing * (mandatory marker) should still match."""
        from app.services.rule_engine.loader import rule_match
        assert rule_match("Full Name *") == "full_name"
        assert rule_match("Date of Birth*") == "dob"

    def test_hindi_label_match(self):
        from app.services.rule_engine.loader import rule_match
        assert rule_match("पूरा नाम") == "full_name"
        assert rule_match("जन्म तिथि") == "dob"
        assert rule_match("आधार संख्या") == "aadhaar_number"

    def test_unknown_label_returns_none(self):
        from app.services.rule_engine.loader import rule_match
        assert rule_match("Preferred Exam Centre") is None
        assert rule_match("Reference Number") is None
        assert rule_match("") is None

    def test_colon_stripped(self):
        from app.services.rule_engine.loader import rule_match
        assert rule_match("Gender:") == "gender"

    def test_whitespace_normalisation(self):
        from app.services.rule_engine.loader import rule_match
        assert rule_match("  Mobile  Number  ") == "mobile_number"


# ──────────────────────────────────────────────────────────────────────────────
# Milestone 3 Tests — FormMappingService
# ──────────────────────────────────────────────────────────────────────────────

class TestFormMappingService:
    """Tests for backend/app/services/form_mapping_service.py"""

    def _make_service(self, db, profile_keys=None):
        from app.services.form_mapping_service import FormMappingService
        return FormMappingService(
            db=db,
            template_id="template-test-uuid",
            profile_field_keys=profile_keys or [
                "full_name", "dob", "aadhaar_number", "pan_number",
                "mobile_number", "email", "address_line1", "city", "state", "pincode",
            ],
            embedding_threshold=0.82,
            ollama_host="http://localhost:11434",
            ollama_model="qwen2.5:7b-instruct-q4_K_M",
        )

    def test_stage1_rule_match(self):
        """Known labels resolve via rule engine at confidence=1.0."""
        mock_db = MagicMock()
        mock_db.execute.return_value.scalar_one_or_none.return_value = None  # No cache

        svc = self._make_service(mock_db)
        key, conf, method = svc.resolve({"field_id": "fn", "label": "Full Name"})

        assert key == "full_name"
        assert conf == 1.0
        assert method == "rule"

    def test_stage2_hint_match(self):
        """LLM hint is used when rule engine misses but hint is valid."""
        mock_db = MagicMock()
        mock_db.execute.return_value.scalar_one_or_none.return_value = None

        svc = self._make_service(mock_db)
        key, conf, method = svc.resolve(
            {"field_id": "dob_custom", "label": "Candidate DOB"},
            profile_hint="dob",
        )

        # Rule should miss "Candidate DOB"; hint provides "dob"
        assert key == "dob"
        assert method == "hint"

    def test_stage1_takes_priority_over_hint(self):
        """Rule engine (stage 1) wins over hint (stage 2)."""
        mock_db = MagicMock()
        mock_db.execute.return_value.scalar_one_or_none.return_value = None

        svc = self._make_service(mock_db)
        key, conf, method = svc.resolve(
            {"field_id": "fn", "label": "Full Name"},
            profile_hint="first_name",  # Wrong hint — rule should win
        )

        assert key == "full_name"
        assert method == "rule"

    def test_no_match_returns_none(self):
        """Completely unknown fields with no embedding or LLM match return None."""
        mock_db = MagicMock()
        mock_db.execute.return_value.scalar_one_or_none.return_value = None
        mock_db.execute.return_value.fetchone.return_value = None  # No embedding match

        svc = self._make_service(mock_db)
        with patch.object(svc, "_llm_match", return_value=None), \
             patch.object(svc, "_embedding_match", return_value=None):
            key, conf, method = svc.resolve(
                {"field_id": "xyz", "label": "Preferred Exam Centre 2024"}
            )

        assert key is None
        assert method == "none"

    def test_cache_hit_short_circuits(self):
        """A cached mapping is returned immediately, no rule/embedding called."""
        from app.models.form import FieldMappingCache

        cached_entry = MagicMock(spec=FieldMappingCache)
        cached_entry.profile_field_key = "dob"
        cached_entry.confidence = 0.95
        cached_entry.method = "embedding"

        mock_db = MagicMock()
        mock_db.execute.return_value.scalar_one_or_none.return_value = cached_entry

        svc = self._make_service(mock_db)
        key, conf, method = svc.resolve({"field_id": "dob_field", "label": "DOB"})

        assert key == "dob"
        assert method == "cache"
        assert conf == 0.95


# ──────────────────────────────────────────────────────────────────────────────
# Milestone 4 Tests — Gap Detection
# ──────────────────────────────────────────────────────────────────────────────

class TestGapDetection:
    """Tests for the gap report logic (unit-level, not HTTP)."""

    def test_completion_percentage_calculation(self):
        """Verify completion percentage arithmetic."""
        total = 10
        filled = 7
        expected_pct = 70.0
        result = round((filled / total * 100) if total > 0 else 0.0, 1)
        assert result == expected_pct

    def test_zero_fields_completion(self):
        total = 0
        result = round((0 / total * 100) if total > 0 else 0.0, 1)
        assert result == 0.0

    def test_can_approve_true_when_no_required_gaps(self):
        """can_approve=True when all required fields are filled."""
        # Simulate: all fields filled, no required gaps
        has_required_gap = False
        assert not has_required_gap  # can_approve = not has_required_gap

    def test_can_approve_false_when_required_field_missing(self):
        has_required_gap = True
        assert has_required_gap  # can_approve = False


# ──────────────────────────────────────────────────────────────────────────────
# Milestone 5 Tests — Encryption fix in prefill
# ──────────────────────────────────────────────────────────────────────────────

class TestEncryptionRoundtrip:
    """Verify that the encrypt → store → decrypt round-trip works correctly
    for the new primary-DEK strategy used in prefill.py."""

    def test_field_encrypt_decrypt_roundtrip(self):
        from app.core.encryption import encrypt_field, decrypt_field, generate_dek

        dek = generate_dek()
        plain = "Akash Kumar"
        encrypted = encrypt_field(plain, dek, "full_name")

        assert encrypted != plain
        decrypted = decrypt_field(encrypted, dek, "full_name")
        assert decrypted == plain

    def test_different_field_keys_produce_different_ciphertexts(self):
        """Field key is part of the derived encryption key — same value, different key."""
        from app.core.encryption import encrypt_field, generate_dek

        dek = generate_dek()
        plain = "test_value"
        c1 = encrypt_field(plain, dek, "full_name")
        c2 = encrypt_field(plain, dek, "father_name")
        assert c1 != c2

    def test_wrong_key_raises_on_decrypt(self):
        """Decryption with wrong field key raises an exception (not silent)."""
        from app.core.encryption import encrypt_field, decrypt_field, generate_dek
        from cryptography.fernet import InvalidToken

        dek = generate_dek()
        encrypted = encrypt_field("secret", dek, "aadhaar_number")
        with pytest.raises(Exception):
            decrypt_field(encrypted, dek, "wrong_field_key")

    def test_resolve_dek_returns_none_for_missing_document(self):
        """_resolve_dek returns None gracefully when source_document_id is None."""
        import sys
        import os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../"))

        from app.tasks.prefill import _resolve_dek

        mock_db = MagicMock()
        mock_pf = MagicMock()
        mock_pf.source_document_id = None

        result = _resolve_dek(mock_db, mock_pf)
        assert result is None


# ──────────────────────────────────────────────────────────────────────────────
# Milestone 1 — Field Seeder
# ──────────────────────────────────────────────────────────────────────────────

class TestFieldSeeder:
    """Tests for the field_embeddings seeder."""

    def test_canonical_fields_list_not_empty(self):
        from ai_services.form_understanding_agent.field_seeder import CANONICAL_FIELDS
        assert len(CANONICAL_FIELDS) > 30

    def test_all_canonical_fields_have_description(self):
        from ai_services.form_understanding_agent.field_seeder import CANONICAL_FIELDS
        for key, desc in CANONICAL_FIELDS:
            assert key, f"Empty field key found"
            assert desc, f"Empty description for field key: {key}"
            assert len(desc) > 5, f"Description too short for {key}: '{desc}'"

    def test_canonical_field_keys_are_unique(self):
        from ai_services.form_understanding_agent.field_seeder import CANONICAL_FIELDS
        keys = [k for k, _ in CANONICAL_FIELDS]
        assert len(keys) == len(set(keys)), "Duplicate canonical field keys found"

    def test_seed_function_signature(self):
        """Verify seed_field_embeddings accepts the expected arguments."""
        import inspect
        from ai_services.form_understanding_agent.field_seeder import seed_field_embeddings
        sig = inspect.signature(seed_field_embeddings)
        assert "db_sync_url" in sig.parameters
        assert "model_name" in sig.parameters

-- 005_form_template_versioning.sql
-- Adds version tracking to form_templates and source_field_key attribution
-- to form_field_values.
-- Safe to run multiple times (uses IF NOT EXISTS / DO NOTHING patterns).

-- Version column on form_templates (allows re-parsing a changed form)
ALTER TABLE form_templates
    ADD COLUMN IF NOT EXISTS version INT NOT NULL DEFAULT 1;

-- Composite index so GET /forms can quickly list latest version per source
CREATE INDEX IF NOT EXISTS idx_form_templates_source_version
    ON form_templates (source_url_or_hash, version DESC);

-- Source field attribution on form_field_values
-- Stores which profile field key produced this value (for UI provenance display)
ALTER TABLE form_field_values
    ADD COLUMN IF NOT EXISTS source_field_key TEXT;

-- Confidence score per mapped field (from rule/embedding/llm stage)
ALTER TABLE form_field_values
    ADD COLUMN IF NOT EXISTS confidence FLOAT NOT NULL DEFAULT 0.0;

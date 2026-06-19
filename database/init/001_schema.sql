-- ============================================================
-- AutoFormFiller Database Schema
-- PostgreSQL 16 + pgvector + pgcrypto
-- ============================================================

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ===================== USERS & PROFILES =====================

CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT UNIQUE,
    phone TEXT UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'user',
    mfa_enabled BOOLEAN NOT NULL DEFAULT false,
    is_verified BOOLEAN NOT NULL DEFAULT false,
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT email_or_phone CHECK (email IS NOT NULL OR phone IS NOT NULL)
);
CREATE INDEX idx_users_email ON users(email);
CREATE INDEX idx_users_phone ON users(phone);

CREATE TABLE profiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    display_name TEXT NOT NULL,
    relation_to_account TEXT NOT NULL DEFAULT 'self',
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_profiles_user_id ON profiles(user_id);

-- ===================== DOCUMENT VAULT =====================

CREATE TABLE documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    profile_id UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    doc_type TEXT NOT NULL,
    storage_key TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    encryption_key_id TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    size_bytes INT NOT NULL,
    version INT NOT NULL DEFAULT 1,
    is_current BOOLEAN NOT NULL DEFAULT true,
    uploaded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_hint_at TIMESTAMPTZ,
    original_filename TEXT,
    processing_status TEXT NOT NULL DEFAULT 'processing'
);
CREATE INDEX idx_documents_profile_id ON documents(profile_id);
CREATE INDEX idx_documents_content_hash ON documents(content_hash);
CREATE INDEX idx_documents_profile_type_current ON documents(profile_id, doc_type) WHERE is_current = true;

CREATE TABLE document_extractions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    raw_blocks JSONB,
    structured_fields JSONB NOT NULL DEFAULT '{}',
    ocr_confidence FLOAT,
    language_detected TEXT,
    model_used TEXT NOT NULL,
    extracted_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_doc_extractions_document_id ON document_extractions(document_id);

CREATE TABLE document_verifications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    overall_flag TEXT NOT NULL DEFAULT 'ok',
    checks JSONB NOT NULL DEFAULT '[]',
    verified_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_doc_verifications_document_id ON document_verifications(document_id);

-- ===================== UNIFIED PROFILE =====================

CREATE TABLE profile_fields (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    profile_id UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    field_key TEXT NOT NULL,
    field_value_encrypted TEXT NOT NULL,
    source_document_id UUID REFERENCES documents(id) ON DELETE SET NULL,
    confidence FLOAT NOT NULL DEFAULT 1.0,
    user_confirmed BOOLEAN NOT NULL DEFAULT false,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (profile_id, field_key)
);
CREATE INDEX idx_profile_fields_profile_id ON profile_fields(profile_id);

CREATE TABLE field_embeddings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    field_key TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL,
    embedding VECTOR(384) NOT NULL
);
CREATE INDEX idx_field_embeddings_vector ON field_embeddings
    USING hnsw (embedding vector_cosine_ops);

-- Conflict queue for cross-document field disagreements
CREATE TABLE profile_field_conflicts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    profile_id UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    field_key TEXT NOT NULL,
    existing_value_encrypted TEXT NOT NULL,
    new_value_encrypted TEXT NOT NULL,
    existing_source_doc_id UUID REFERENCES documents(id) ON DELETE SET NULL,
    new_source_doc_id UUID REFERENCES documents(id) ON DELETE SET NULL,
    resolved BOOLEAN NOT NULL DEFAULT false,
    chosen_value_encrypted TEXT,
    resolved_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_profile_conflicts_profile ON profile_field_conflicts(profile_id) WHERE resolved = false;

-- ===================== FORMS =====================

CREATE TABLE form_templates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_type TEXT NOT NULL,
    source_url_or_hash TEXT NOT NULL UNIQUE,
    field_schema JSONB NOT NULL DEFAULT '[]',
    upload_slots JSONB NOT NULL DEFAULT '[]',
    scheme_id UUID,
    scheme_name TEXT,
    last_validated_at TIMESTAMPTZ,
    parsed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_form_templates_hash ON form_templates(source_url_or_hash);

CREATE TABLE field_mapping_cache (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    form_template_id UUID NOT NULL REFERENCES form_templates(id) ON DELETE CASCADE,
    form_field_id TEXT NOT NULL,
    profile_field_key TEXT,
    confidence FLOAT NOT NULL,
    method TEXT NOT NULL,
    llm_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (form_template_id, form_field_id)
);
CREATE INDEX idx_field_mapping_cache_template ON field_mapping_cache(form_template_id);

CREATE TABLE form_instances (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    form_template_id UUID NOT NULL REFERENCES form_templates(id),
    profile_id UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    workflow_run_id UUID,
    status TEXT NOT NULL DEFAULT 'draft',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    submitted_at TIMESTAMPTZ,
    reference_number TEXT
);
CREATE INDEX idx_form_instances_profile_id ON form_instances(profile_id);
CREATE INDEX idx_form_instances_status ON form_instances(status);

CREATE TABLE form_field_values (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    form_instance_id UUID NOT NULL REFERENCES form_instances(id) ON DELETE CASCADE,
    form_field_id TEXT NOT NULL,
    value_encrypted TEXT,
    method TEXT NOT NULL DEFAULT 'rule',
    human_reviewed BOOLEAN NOT NULL DEFAULT false,
    needs_attention BOOLEAN NOT NULL DEFAULT false,
    attention_reason TEXT,
    UNIQUE (form_instance_id, form_field_id)
);
CREATE INDEX idx_form_field_values_instance ON form_field_values(form_instance_id);

-- ===================== WORKFLOW & TRACKING =====================

CREATE TABLE workflow_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    profile_id UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    trigger_type TEXT NOT NULL,
    trigger_ref_id UUID,
    current_state TEXT NOT NULL,
    history JSONB NOT NULL DEFAULT '[]',
    retry_counts JSONB NOT NULL DEFAULT '{}',
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_workflow_runs_profile_id ON workflow_runs(profile_id);
CREATE INDEX idx_workflow_runs_state ON workflow_runs(current_state);

CREATE TABLE application_status_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    form_instance_id UUID NOT NULL REFERENCES form_instances(id) ON DELETE CASCADE,
    status TEXT NOT NULL,
    note TEXT,
    changed_by TEXT NOT NULL DEFAULT 'system',
    changed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_app_status_log_instance ON application_status_log(form_instance_id);

-- ===================== CONSENT & AUDIT =====================

CREATE TABLE consent_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    profile_id UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    action TEXT NOT NULL,
    scope TEXT NOT NULL,
    granted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_at TIMESTAMPTZ
);
CREATE INDEX idx_consent_log_profile_id ON consent_log(profile_id);

CREATE TABLE audit_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    profile_id UUID REFERENCES profiles(id) ON DELETE SET NULL,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    details JSONB,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_audit_log_profile_id ON audit_log(profile_id);
CREATE INDEX idx_audit_log_occurred_at ON audit_log(occurred_at);

-- ===================== RAG KNOWLEDGE BASE =====================

CREATE TABLE rag_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scheme_id UUID,
    scheme_name TEXT,
    source_url TEXT,
    chunk_text TEXT NOT NULL,
    embedding VECTOR(384) NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_rag_chunks_vector ON rag_chunks
    USING hnsw (embedding vector_cosine_ops);
CREATE INDEX idx_rag_chunks_scheme ON rag_chunks(scheme_id);

-- ===================== OTP & SESSIONS =====================

CREATE TABLE otp_tokens (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL,
    purpose TEXT NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    used BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_otp_tokens_user ON otp_tokens(user_id);

CREATE TABLE refresh_tokens (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL UNIQUE,
    expires_at TIMESTAMPTZ NOT NULL,
    revoked BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_refresh_tokens_user ON refresh_tokens(user_id);
CREATE INDEX idx_refresh_tokens_hash ON refresh_tokens(token_hash);

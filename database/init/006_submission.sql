-- =====================================================================
-- Migration 006: Phase 3 — Portal Submission
-- Adds submission_runs, submission_audit_entries, and extends
-- form_instances with portal submission tracking columns.
-- =====================================================================

-- ===================== SUBMISSION RUNS =====================

CREATE TABLE IF NOT EXISTS submission_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    form_instance_id UUID NOT NULL REFERENCES form_instances(id) ON DELETE CASCADE,
    portal_adapter TEXT NOT NULL,           -- 'mock_portal' | 'nsp_scholarship' | etc.
    status TEXT NOT NULL DEFAULT 'pending', -- pending | running | awaiting_user | completed | failed
    checkpoint JSONB DEFAULT '{}' NOT NULL, -- resumable browser state (storage_state + last_step)
    screenshot_keys TEXT[] DEFAULT '{}',    -- MinIO object keys for captured screenshots
    portal_reference TEXT,                  -- application reference number returned by portal
    error_detail TEXT,                      -- last error message for failed runs
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,
    -- Human approval tracking (stored on the run, not just the instance)
    approved_by TEXT,                       -- user_id who triggered submission
    approved_at TIMESTAMPTZ,
    approval_version INT NOT NULL DEFAULT 1 -- increments on each re-approval cycle
);

CREATE INDEX IF NOT EXISTS idx_submission_runs_instance
    ON submission_runs(form_instance_id);

CREATE INDEX IF NOT EXISTS idx_submission_runs_status
    ON submission_runs(status);

-- ===================== FORM INSTANCES EXTENSION =====================

-- Add portal_adapter and submission_run_id columns to existing form_instances
ALTER TABLE form_instances
    ADD COLUMN IF NOT EXISTS portal_adapter TEXT,
    ADD COLUMN IF NOT EXISTS submission_run_id UUID REFERENCES submission_runs(id);

-- ===================== SUBMISSION AUDIT ENTRIES =====================
-- Immutable per-browser-action audit trail — one row per action taken
-- by the Playwright submission engine. Masked values only, never plaintext.

CREATE TABLE IF NOT EXISTS submission_audit_entries (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    submission_run_id UUID NOT NULL REFERENCES submission_runs(id) ON DELETE CASCADE,

    -- Action classification
    action TEXT NOT NULL,
    -- 'navigate' | 'fill_field' | 'click' | 'upload_document' |
    -- 'captcha_detected' | 'captcha_resolved' | 'submit_clicked' |
    -- 'portal_response' | 'error' | 'checkpoint_saved'

    -- Field-level detail (populated for fill_field and upload_document)
    field_id TEXT,
    masked_value TEXT,          -- Sensitive values masked (e.g. "XXXX-XXXX-1234")

    -- Evidence
    screenshot_key TEXT,        -- MinIO key if a screenshot was taken for this action
    portal_response TEXT,       -- Relevant portal response text (e.g. error message, ref number)
    extra JSONB DEFAULT '{}',   -- Additional action-specific metadata

    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_sub_audit_run
    ON submission_audit_entries(submission_run_id);

CREATE INDEX IF NOT EXISTS idx_sub_audit_occurred
    ON submission_audit_entries(occurred_at);

-- Prevent any UPDATE or DELETE on submission_audit_entries for non-superusers
-- (append-only enforcement — matches audit_log policy in Phase 1)
CREATE OR REPLACE RULE submission_audit_no_update AS
    ON UPDATE TO submission_audit_entries DO INSTEAD NOTHING;

CREATE OR REPLACE RULE submission_audit_no_delete AS
    ON DELETE TO submission_audit_entries DO INSTEAD NOTHING;

-- ===================== COMMENTS =====================

COMMENT ON TABLE submission_runs IS
    'One row per automated portal submission attempt. Tracks lifecycle from '
    'pending through running/awaiting_user to completed or failed. '
    'Supports checkpoint-based resumption.';

COMMENT ON TABLE submission_audit_entries IS
    'Immutable per-browser-action audit trail for submission runs. '
    'Sensitive field values are masked before storage. '
    'Append-only enforced via Postgres rules.';

COMMENT ON COLUMN submission_runs.checkpoint IS
    'JSON blob containing Playwright browser storage_state and the '
    'index of the last successfully completed submission step. '
    'Used by submission_recovery.py to resume failed runs.';

COMMENT ON COLUMN submission_audit_entries.masked_value IS
    'Field value with sensitive portions masked per mask_sensitive_value() '
    'utility. Example: Aadhaar "1234 5678 9012" becomes "XXXX XXXX 9012". '
    'Plaintext values are never stored in this column.';

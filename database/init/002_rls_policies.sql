-- ============================================================
-- Row-Level Security Policies
-- AutoFormFiller — enforces profile-level data isolation at DB layer
-- ============================================================

-- Enable RLS on all profile-scoped tables
ALTER TABLE profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE document_extractions ENABLE ROW LEVEL SECURITY;
ALTER TABLE document_verifications ENABLE ROW LEVEL SECURITY;
ALTER TABLE profile_fields ENABLE ROW LEVEL SECURITY;
ALTER TABLE profile_field_conflicts ENABLE ROW LEVEL SECURITY;
ALTER TABLE form_instances ENABLE ROW LEVEL SECURITY;
ALTER TABLE form_field_values ENABLE ROW LEVEL SECURITY;
ALTER TABLE workflow_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE consent_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY;

-- Helper: get current profile ID from session variable
-- Set by the API layer on every request: SET app.current_profile_id = '<uuid>'
-- For system/admin operations: SET app.bypass_rls = 'true'

-- Profiles: user can only see their own profiles
CREATE POLICY profiles_isolation ON profiles
    FOR ALL
    USING (
        current_setting('app.bypass_rls', true) = 'true'
        OR user_id = current_setting('app.current_user_id', true)::uuid
    );

-- Documents: profile-scoped
CREATE POLICY documents_isolation ON documents
    FOR ALL
    USING (
        current_setting('app.bypass_rls', true) = 'true'
        OR profile_id = current_setting('app.current_profile_id', true)::uuid
    );

-- Document extractions: scoped via document
CREATE POLICY doc_extractions_isolation ON document_extractions
    FOR ALL
    USING (
        current_setting('app.bypass_rls', true) = 'true'
        OR document_id IN (
            SELECT id FROM documents
            WHERE profile_id = current_setting('app.current_profile_id', true)::uuid
        )
    );

-- Document verifications: scoped via document
CREATE POLICY doc_verifications_isolation ON document_verifications
    FOR ALL
    USING (
        current_setting('app.bypass_rls', true) = 'true'
        OR document_id IN (
            SELECT id FROM documents
            WHERE profile_id = current_setting('app.current_profile_id', true)::uuid
        )
    );

-- Profile fields
CREATE POLICY profile_fields_isolation ON profile_fields
    FOR ALL
    USING (
        current_setting('app.bypass_rls', true) = 'true'
        OR profile_id = current_setting('app.current_profile_id', true)::uuid
    );

-- Profile conflicts
CREATE POLICY profile_conflicts_isolation ON profile_field_conflicts
    FOR ALL
    USING (
        current_setting('app.bypass_rls', true) = 'true'
        OR profile_id = current_setting('app.current_profile_id', true)::uuid
    );

-- Form instances
CREATE POLICY form_instances_isolation ON form_instances
    FOR ALL
    USING (
        current_setting('app.bypass_rls', true) = 'true'
        OR profile_id = current_setting('app.current_profile_id', true)::uuid
    );

-- Form field values: scoped via form_instance
CREATE POLICY form_field_values_isolation ON form_field_values
    FOR ALL
    USING (
        current_setting('app.bypass_rls', true) = 'true'
        OR form_instance_id IN (
            SELECT id FROM form_instances
            WHERE profile_id = current_setting('app.current_profile_id', true)::uuid
        )
    );

-- Workflow runs
CREATE POLICY workflow_runs_isolation ON workflow_runs
    FOR ALL
    USING (
        current_setting('app.bypass_rls', true) = 'true'
        OR profile_id = current_setting('app.current_profile_id', true)::uuid
    );

-- Consent log
CREATE POLICY consent_log_isolation ON consent_log
    FOR ALL
    USING (
        current_setting('app.bypass_rls', true) = 'true'
        OR profile_id = current_setting('app.current_profile_id', true)::uuid
    );

-- Audit log: read own, system can read all
CREATE POLICY audit_log_isolation ON audit_log
    FOR SELECT
    USING (
        current_setting('app.bypass_rls', true) = 'true'
        OR profile_id = current_setting('app.current_profile_id', true)::uuid
    );

-- Audit log: append-only (no UPDATE or DELETE by regular roles)
CREATE POLICY audit_log_append_only ON audit_log
    FOR INSERT
    WITH CHECK (true);

-- Block UPDATE/DELETE on audit_log (enforced via trigger below)

-- ============================================================
-- Audit & Integrity Triggers
-- ============================================================

-- Prevent UPDATE/DELETE on audit_log (append-only enforcement)
CREATE OR REPLACE FUNCTION prevent_audit_log_modification()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'audit_log is append-only. UPDATE and DELETE are not permitted. Actor: %', current_user;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER audit_log_no_update
    BEFORE UPDATE ON audit_log
    FOR EACH ROW
    EXECUTE FUNCTION prevent_audit_log_modification();

CREATE TRIGGER audit_log_no_delete
    BEFORE DELETE ON audit_log
    FOR EACH ROW
    EXECUTE FUNCTION prevent_audit_log_modification();

-- Auto-update updated_at timestamps
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER users_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER profile_fields_updated_at
    BEFORE UPDATE ON profile_fields
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER workflow_runs_updated_at
    BEFORE UPDATE ON workflow_runs
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Auto-log application status changes to audit_log
CREATE OR REPLACE FUNCTION log_form_status_change()
RETURNS TRIGGER AS $$
BEGIN
    IF OLD.status IS DISTINCT FROM NEW.status THEN
        INSERT INTO audit_log (profile_id, actor, action, details)
        SELECT
            fi.profile_id,
            'system:orchestrator',
            'form_status_changed',
            jsonb_build_object(
                'form_instance_id', NEW.id,
                'old_status', OLD.status,
                'new_status', NEW.status
            )
        FROM form_instances fi WHERE fi.id = NEW.id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER form_instance_status_audit
    AFTER UPDATE OF status ON form_instances
    FOR EACH ROW
    EXECUTE FUNCTION log_form_status_change();

-- Mark old document versions as not current on new upload
CREATE OR REPLACE FUNCTION mark_old_doc_versions()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.is_current = true THEN
        UPDATE documents
        SET is_current = false
        WHERE profile_id = NEW.profile_id
          AND doc_type = NEW.doc_type
          AND id != NEW.id
          AND is_current = true;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER documents_version_management
    AFTER INSERT ON documents
    FOR EACH ROW
    EXECUTE FUNCTION mark_old_doc_versions();

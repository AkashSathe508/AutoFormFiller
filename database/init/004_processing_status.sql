-- Add processing_status for document pipeline tracking (existing deployments)
ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS processing_status TEXT NOT NULL DEFAULT 'processing';

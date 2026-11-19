-- Retention review marker for private product artifacts.
-- This migration never deletes R2 objects or audit events. Expired artifacts
-- become candidates for a separate, explicitly owner-approved deletion flow.
ALTER TABLE internal_execution_jobs ADD COLUMN retention_review_after TEXT;

UPDATE internal_execution_jobs
SET retention_review_after = strftime('%Y-%m-%dT%H:%M:%fZ', updated_at, '+90 days')
WHERE status = 'delivery_ready' AND artifact_key IS NOT NULL
  AND retention_review_after IS NULL;

CREATE TRIGGER IF NOT EXISTS trg_internal_execution_artifact_retention
AFTER UPDATE OF status ON internal_execution_jobs
WHEN NEW.status = 'delivery_ready'
  AND OLD.status <> 'delivery_ready'
  AND NEW.artifact_key IS NOT NULL
BEGIN
  UPDATE internal_execution_jobs
  SET retention_review_after = strftime('%Y-%m-%dT%H:%M:%fZ', NEW.updated_at, '+90 days')
  WHERE job_id = NEW.job_id;
END;

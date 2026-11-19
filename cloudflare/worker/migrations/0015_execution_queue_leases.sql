-- Recover approved cloud builds after a scheduled Worker invocation is interrupted.
ALTER TABLE internal_execution_jobs ADD COLUMN attempt_count INTEGER NOT NULL DEFAULT 0 CHECK(attempt_count >= 0);
ALTER TABLE internal_execution_jobs ADD COLUMN lease_expires_at TEXT;
CREATE INDEX IF NOT EXISTS idx_internal_execution_jobs_queue
  ON internal_execution_jobs(status,lease_expires_at,created_at);

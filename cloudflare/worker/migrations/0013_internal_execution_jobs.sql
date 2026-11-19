-- Private, owner-triggered internal product executions and immutable delivery evidence.
CREATE TABLE IF NOT EXISTS internal_execution_jobs (
  job_id TEXT PRIMARY KEY,
  owner_id TEXT NOT NULL,
  idempotency_key TEXT NOT NULL,
  agent_id TEXT NOT NULL CHECK(agent_id = 'game-asset-builder'),
  execution_spec_json TEXT NOT NULL CHECK(execution_spec_json = '{"kind":"moba_objective_props_v1"}'),
  status TEXT NOT NULL CHECK(status IN ('approved','running','delivery_ready','failed')),
  artifact_key TEXT,
  artifact_sha256 TEXT,
  artifact_size_bytes INTEGER,
  error_code TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(owner_id,idempotency_key),
  FOREIGN KEY(owner_id) REFERENCES financial_participants(participant_id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS idx_internal_execution_jobs_owner_created
  ON internal_execution_jobs(owner_id,created_at DESC);

CREATE TABLE IF NOT EXISTS internal_execution_events (
  event_id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL,
  owner_id TEXT NOT NULL,
  event_type TEXT NOT NULL CHECK(event_type IN ('owner_approved','execution_started','artifact_verified','execution_failed')),
  evidence_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY(job_id) REFERENCES internal_execution_jobs(job_id) ON DELETE RESTRICT,
  FOREIGN KEY(owner_id) REFERENCES financial_participants(participant_id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS idx_internal_execution_events_job
  ON internal_execution_events(job_id,created_at);

CREATE TRIGGER IF NOT EXISTS trg_internal_execution_events_no_update
BEFORE UPDATE ON internal_execution_events
BEGIN SELECT RAISE(ABORT,'execution audit events are append-only'); END;
CREATE TRIGGER IF NOT EXISTS trg_internal_execution_events_no_delete
BEFORE DELETE ON internal_execution_events
BEGIN SELECT RAISE(ABORT,'execution audit events are append-only'); END;

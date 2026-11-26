-- Append-only evidence for the AAE task lifecycle. No external task action is represented
-- unless a separate evidence-backed event is explicitly recorded.
CREATE TABLE IF NOT EXISTS aae_task_lifecycle_events (
  event_id TEXT PRIMARY KEY,
  source TEXT NOT NULL,
  external_task_id TEXT NOT NULL,
  job_id TEXT,
  status TEXT NOT NULL CHECK(status IN (
    'discovered','qualified','selected','in_progress','qa_passed','submission_ready',
    'blocked','failed','submitted','accepted','rejected','paid'
  )),
  participation_class TEXT NOT NULL CHECK(participation_class IN (
    'discovery_only','human_led','agent_permitted'
  )),
  evidence_json TEXT NOT NULL,
  evidence_hash TEXT NOT NULL,
  recorded_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_aae_task_lifecycle_dedupe
  ON aae_task_lifecycle_events(source,external_task_id,status,evidence_hash);
CREATE INDEX IF NOT EXISTS idx_aae_task_lifecycle_recent
  ON aae_task_lifecycle_events(recorded_at DESC);
CREATE INDEX IF NOT EXISTS idx_aae_task_lifecycle_task
  ON aae_task_lifecycle_events(source,external_task_id,recorded_at DESC);

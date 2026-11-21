CREATE TABLE IF NOT EXISTS aae_execution_jobs (
  job_id TEXT PRIMARY KEY,
  source TEXT NOT NULL,
  external_task_id TEXT NOT NULL,
  title TEXT NOT NULL,
  task_snapshot_json TEXT NOT NULL,
  reward_text TEXT,
  eligibility_json TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('queued','blocked','running','draft_ready','failed','submitted','accepted','rejected')),
  result_text TEXT,
  error TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(source, external_task_id)
);
CREATE INDEX IF NOT EXISTS idx_aae_execution_jobs_status_created
ON aae_execution_jobs(status, created_at);
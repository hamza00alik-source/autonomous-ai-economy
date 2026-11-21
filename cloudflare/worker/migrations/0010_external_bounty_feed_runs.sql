CREATE TABLE IF NOT EXISTS aae_external_bounty_feed_runs (
  run_id TEXT PRIMARY KEY,
  status TEXT NOT NULL CHECK(status IN ('success','skipped','failed')),
  fetched INTEGER NOT NULL DEFAULT 0,
  stored INTEGER NOT NULL DEFAULT 0,
  rejected INTEGER NOT NULL DEFAULT 0,
  feed_generated_at TEXT,
  error TEXT,
  started_at TEXT NOT NULL,
  finished_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_aae_external_bounty_runs_started
  ON aae_external_bounty_feed_runs(started_at DESC);

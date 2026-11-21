CREATE TABLE IF NOT EXISTS aae_external_bounty_discoveries (
  bounty_id TEXT PRIMARY KEY,
  source TEXT NOT NULL,
  title TEXT NOT NULL,
  source_url TEXT NOT NULL,
  reward_usd REAL NOT NULL,
  currency TEXT NOT NULL,
  requirements_json TEXT NOT NULL,
  deadline TEXT,
  verified_at TEXT,
  feed_generated_at TEXT NOT NULL,
  snapshot_json TEXT NOT NULL,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_aae_external_bounties_reward_deadline
  ON aae_external_bounty_discoveries(reward_usd DESC, deadline);

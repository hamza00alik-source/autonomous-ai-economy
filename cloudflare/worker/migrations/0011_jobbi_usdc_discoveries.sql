ALTER TABLE aae_external_bounty_feed_runs
  ADD COLUMN source TEXT NOT NULL DEFAULT 'agent_bounty_feed';

CREATE TABLE IF NOT EXISTS aae_jobbi_discoveries (
  gig_id TEXT PRIMARY KEY,
  board_source TEXT NOT NULL,
  title TEXT NOT NULL,
  source_url TEXT NOT NULL,
  reward_usd REAL NOT NULL,
  currency TEXT NOT NULL,
  payment_rail TEXT NOT NULL,
  payment_state TEXT NOT NULL,
  payout_grade TEXT NOT NULL,
  acceptance_type TEXT,
  requirements_json TEXT NOT NULL,
  deadline TEXT,
  verified_at TEXT NOT NULL,
  feed_fetched_at TEXT NOT NULL,
  snapshot_json TEXT NOT NULL,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_aae_jobbi_discoveries_reward
  ON aae_jobbi_discoveries(reward_usd DESC, payout_grade, last_seen_at DESC);

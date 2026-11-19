-- One-time proof-of-possession challenge for the cloud owner/operator enrollment.
-- The owner ID and operator ID are configured out-of-band; the key is never uploaded.
CREATE TABLE IF NOT EXISTS financial_owner_enrollment_challenges (
  challenge_id TEXT PRIMARY KEY,
  owner_id TEXT NOT NULL,
  operator_id TEXT NOT NULL,
  challenge TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  consumed_at TEXT,
  created_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_financial_owner_enrollment_one_pending
  ON financial_owner_enrollment_challenges(owner_id)
  WHERE consumed_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_financial_owner_enrollment_expiry
  ON financial_owner_enrollment_challenges(expires_at, consumed_at);

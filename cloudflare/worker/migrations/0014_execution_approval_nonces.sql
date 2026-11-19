-- Single-use, owner-signed authorization evidence for private internal product builds.
CREATE TABLE IF NOT EXISTS internal_execution_approval_nonces (
  owner_id TEXT NOT NULL,
  nonce TEXT NOT NULL,
  idempotency_key TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  consumed_at TEXT NOT NULL,
  PRIMARY KEY(owner_id,nonce),
  FOREIGN KEY(owner_id) REFERENCES financial_participants(participant_id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS idx_internal_execution_approval_expiry
  ON internal_execution_approval_nonces(expires_at);
CREATE TRIGGER IF NOT EXISTS trg_internal_execution_approval_nonce_no_update
BEFORE UPDATE ON internal_execution_approval_nonces
BEGIN SELECT RAISE(ABORT,'execution approval nonce records are immutable'); END;
CREATE TRIGGER IF NOT EXISTS trg_internal_execution_approval_nonce_no_delete
BEFORE DELETE ON internal_execution_approval_nonces
BEGIN SELECT RAISE(ABORT,'execution approval nonce history is retained'); END;

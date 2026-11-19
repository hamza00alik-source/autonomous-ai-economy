-- Per-agent Ed25519 API identities. Private keys are generated and retained by agent runtimes.
CREATE TABLE IF NOT EXISTS financial_agent_api_keys (
  key_id TEXT PRIMARY KEY,
  owner_id TEXT NOT NULL,
  agent_id TEXT NOT NULL,
  public_key_jwk TEXT NOT NULL,
  key_fingerprint TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('active','revoked')),
  created_at TEXT NOT NULL,
  revoked_at TEXT,
  FOREIGN KEY(owner_id) REFERENCES financial_participants(participant_id) ON DELETE RESTRICT,
  FOREIGN KEY(agent_id) REFERENCES financial_participants(participant_id) ON DELETE RESTRICT,
  UNIQUE(owner_id,agent_id,key_fingerprint)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_financial_agent_api_one_active
  ON financial_agent_api_keys(owner_id,agent_id) WHERE status='active';
CREATE TABLE IF NOT EXISTS financial_agent_api_nonces (
  key_id TEXT NOT NULL,
  nonce TEXT NOT NULL,
  request_timestamp INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY(key_id,nonce),
  FOREIGN KEY(key_id) REFERENCES financial_agent_api_keys(key_id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS idx_financial_agent_api_nonces_time
  ON financial_agent_api_nonces(created_at);
CREATE TRIGGER IF NOT EXISTS trg_financial_agent_api_key_no_delete
BEFORE DELETE ON financial_agent_api_keys
BEGIN SELECT RAISE(ABORT,'agent API key history is retained'); END;
CREATE TRIGGER IF NOT EXISTS trg_financial_agent_api_nonce_no_update
BEFORE UPDATE ON financial_agent_api_nonces
BEGIN SELECT RAISE(ABORT,'agent API nonce history is immutable'); END;

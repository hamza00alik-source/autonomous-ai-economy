-- Persist evidence for independently verified Base USDC invoice payments.
-- No funds are credited to the financial journal by this migration or verifier.

CREATE TABLE IF NOT EXISTS financial_receiving_payment_observations (
  observation_id TEXT PRIMARY KEY,
  owner_id TEXT NOT NULL,
  agent_id TEXT NOT NULL,
  invoice_id TEXT NOT NULL UNIQUE,
  network TEXT NOT NULL CHECK (network='base-mainnet'),
  tx_hash TEXT NOT NULL CHECK (length(tx_hash)=66 AND substr(tx_hash,1,2)='0x'),
  block_number INTEGER NOT NULL CHECK (block_number>=0),
  block_hash TEXT NOT NULL CHECK (length(block_hash)=66 AND substr(block_hash,1,2)='0x'),
  amount_minor INTEGER NOT NULL CHECK (amount_minor>=0),
  matched_log_indices_json TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('confirmed','review')),
  evidence_json TEXT NOT NULL,
  observed_at TEXT NOT NULL,
  FOREIGN KEY (owner_id) REFERENCES financial_participants(participant_id) ON DELETE RESTRICT,
  FOREIGN KEY (agent_id) REFERENCES financial_participants(participant_id) ON DELETE RESTRICT,
  FOREIGN KEY (invoice_id) REFERENCES financial_receiving_invoices(invoice_id) ON DELETE RESTRICT,
  UNIQUE(network,tx_hash)
);

CREATE INDEX IF NOT EXISTS idx_financial_receiving_observations_agent
  ON financial_receiving_payment_observations(owner_id,agent_id,status,observed_at DESC);

CREATE TRIGGER IF NOT EXISTS trg_financial_receiving_observations_no_update
BEFORE UPDATE ON financial_receiving_payment_observations
BEGIN SELECT RAISE(ABORT,'payment observation evidence is immutable'); END;

CREATE TRIGGER IF NOT EXISTS trg_financial_receiving_observations_no_delete
BEFORE DELETE ON financial_receiving_payment_observations
BEGIN SELECT RAISE(ABORT,'payment observation evidence is retained'); END;

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

-- Insert only against an invoice that is still awaiting payment; atomically
-- advance the invoice to confirmed or review with the immutable observation.
CREATE TRIGGER IF NOT EXISTS trg_financial_receiving_observation_requires_open_invoice
BEFORE INSERT ON financial_receiving_payment_observations
BEGIN
  SELECT CASE WHEN NOT EXISTS (
    SELECT 1 FROM financial_receiving_invoices i
    WHERE i.invoice_id=NEW.invoice_id AND i.owner_id=NEW.owner_id AND i.agent_id=NEW.agent_id
      AND i.network=NEW.network AND i.status='awaiting_payment'
  ) THEN RAISE(ABORT,'receiving invoice is not open for payment observation') END;
END;

CREATE TRIGGER IF NOT EXISTS trg_financial_receiving_observation_updates_invoice
AFTER INSERT ON financial_receiving_payment_observations
BEGIN
  UPDATE financial_receiving_invoices SET status=NEW.status,updated_at=NEW.observed_at
  WHERE invoice_id=NEW.invoice_id AND status='awaiting_payment';
END;

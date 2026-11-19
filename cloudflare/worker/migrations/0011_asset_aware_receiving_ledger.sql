-- Asset-aware ledger for verified Base USDC receipts.
-- This is intentionally separate from the USD-only financial journal.
-- Pending-custody balances are not spendable until wallet control and signing are proven.

CREATE TABLE IF NOT EXISTS financial_asset_accounts (
  account_id TEXT PRIMARY KEY,
  owner_id TEXT NOT NULL,
  agent_id TEXT,
  wallet_id TEXT,
  account_type TEXT NOT NULL CHECK (account_type IN ('agent_pending_custody','agent_pending_revenue','agent_available','agent_reserve','owner_treasury','owner_payable','platform_clearing')),
  network TEXT NOT NULL CHECK (network='base-mainnet'),
  chain_id INTEGER NOT NULL CHECK (chain_id=8453),
  asset_code TEXT NOT NULL CHECK (asset_code='USDC'),
  token_contract TEXT NOT NULL CHECK (lower(token_contract)='0x833589fcD6eDb6E08f4c7C32D4f71b54bdA02913'),
  token_decimals INTEGER NOT NULL CHECK (token_decimals=6),
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','frozen','closed')),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (owner_id) REFERENCES financial_participants(participant_id) ON DELETE RESTRICT,
  FOREIGN KEY (agent_id) REFERENCES financial_participants(participant_id) ON DELETE RESTRICT,
  FOREIGN KEY (wallet_id) REFERENCES financial_agent_receiving_wallets(wallet_id) ON DELETE RESTRICT,
  CHECK (
    (account_type='agent_pending_custody' AND agent_id IS NOT NULL AND wallet_id IS NOT NULL) OR
    (account_type='agent_pending_revenue' AND agent_id IS NOT NULL AND wallet_id IS NULL) OR
    (account_type IN ('agent_available','agent_reserve') AND agent_id IS NOT NULL AND wallet_id IS NULL) OR
    (account_type IN ('owner_treasury','owner_payable','platform_clearing') AND agent_id IS NULL AND wallet_id IS NULL)
  )
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_asset_account_wallet_type
  ON financial_asset_accounts(owner_id,agent_id,wallet_id,account_type,network,asset_code)
  WHERE wallet_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_asset_account_agent_type
  ON financial_asset_accounts(owner_id,agent_id,account_type,network,asset_code)
  WHERE agent_id IS NOT NULL AND wallet_id IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_asset_account_owner_type
  ON financial_asset_accounts(owner_id,account_type,network,asset_code)
  WHERE agent_id IS NULL;

CREATE TABLE IF NOT EXISTS financial_asset_journal_transactions (
  transaction_id TEXT PRIMARY KEY,
  owner_id TEXT NOT NULL,
  idempotency_key TEXT NOT NULL UNIQUE,
  payload_hash TEXT NOT NULL,
  source_type TEXT NOT NULL CHECK (source_type IN ('receiving_payment','custody_release','allocation','expense','reversal')),
  source_reference TEXT NOT NULL,
  network TEXT NOT NULL CHECK (network='base-mainnet'),
  chain_id INTEGER NOT NULL CHECK (chain_id=8453),
  asset_code TEXT NOT NULL CHECK (asset_code='USDC'),
  token_contract TEXT NOT NULL CHECK (lower(token_contract)='0x833589fcD6eDb6E08f4c7C32D4f71b54bdA02913'),
  token_decimals INTEGER NOT NULL CHECK (token_decimals=6),
  status TEXT NOT NULL CHECK (status='posted'),
  description TEXT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY (owner_id) REFERENCES financial_participants(participant_id) ON DELETE RESTRICT,
  UNIQUE(owner_id,source_type,source_reference,network,asset_code)
);

CREATE TABLE IF NOT EXISTS financial_asset_journal_postings (
  transaction_id TEXT NOT NULL,
  line_number INTEGER NOT NULL CHECK (line_number>0),
  account_id TEXT NOT NULL,
  direction TEXT NOT NULL CHECK (direction IN ('debit','credit')),
  amount_minor INTEGER NOT NULL CHECK (amount_minor>0),
  network TEXT NOT NULL CHECK (network='base-mainnet'),
  chain_id INTEGER NOT NULL CHECK (chain_id=8453),
  asset_code TEXT NOT NULL CHECK (asset_code='USDC'),
  token_contract TEXT NOT NULL CHECK (lower(token_contract)='0x833589fcD6eDb6E08f4c7C32D4f71b54bdA02913'),
  token_decimals INTEGER NOT NULL CHECK (token_decimals=6),
  created_at TEXT NOT NULL,
  PRIMARY KEY(transaction_id,line_number),
  FOREIGN KEY (transaction_id) REFERENCES financial_asset_journal_transactions(transaction_id) ON DELETE RESTRICT,
  FOREIGN KEY (account_id) REFERENCES financial_asset_accounts(account_id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_asset_postings_account
  ON financial_asset_journal_postings(account_id,transaction_id);
CREATE INDEX IF NOT EXISTS idx_asset_transactions_owner_created
  ON financial_asset_journal_transactions(owner_id,created_at DESC);

CREATE TRIGGER IF NOT EXISTS trg_asset_posting_matches_account
BEFORE INSERT ON financial_asset_journal_postings
WHEN NOT EXISTS (
  SELECT 1 FROM financial_asset_journal_transactions t
  JOIN financial_asset_accounts a ON a.account_id=NEW.account_id
  WHERE t.transaction_id=NEW.transaction_id AND t.owner_id=a.owner_id
    AND t.network=NEW.network AND t.chain_id=NEW.chain_id AND t.asset_code=NEW.asset_code
    AND lower(t.token_contract)=lower(NEW.token_contract) AND t.token_decimals=NEW.token_decimals
    AND a.network=NEW.network AND a.chain_id=NEW.chain_id AND a.asset_code=NEW.asset_code
    AND lower(a.token_contract)=lower(NEW.token_contract) AND a.token_decimals=NEW.token_decimals
    AND a.status='active'
)
BEGIN SELECT RAISE(ABORT,'asset posting account and transaction identity mismatch'); END;

CREATE TRIGGER IF NOT EXISTS trg_asset_transactions_no_update
BEFORE UPDATE ON financial_asset_journal_transactions
BEGIN SELECT RAISE(ABORT,'posted asset journal transactions are immutable'); END;
CREATE TRIGGER IF NOT EXISTS trg_asset_transactions_no_delete
BEFORE DELETE ON financial_asset_journal_transactions
BEGIN SELECT RAISE(ABORT,'posted asset journal transactions are immutable'); END;
CREATE TRIGGER IF NOT EXISTS trg_asset_postings_no_update
BEFORE UPDATE ON financial_asset_journal_postings
BEGIN SELECT RAISE(ABORT,'posted asset journal postings are immutable'); END;
CREATE TRIGGER IF NOT EXISTS trg_asset_postings_no_delete
BEFORE DELETE ON financial_asset_journal_postings
BEGIN SELECT RAISE(ABORT,'posted asset journal postings are immutable'); END;

-- Only a confirmed immutable chain observation may be reflected as pending custody.
CREATE TRIGGER IF NOT EXISTS trg_asset_receiving_payment_requires_confirmed_evidence
BEFORE INSERT ON financial_asset_journal_transactions
WHEN NEW.source_type='receiving_payment'
BEGIN
  SELECT CASE WHEN NOT EXISTS (
    SELECT 1 FROM financial_receiving_payment_observations o
    WHERE o.invoice_id=NEW.source_reference AND o.owner_id=NEW.owner_id
      AND o.network=NEW.network AND o.status='confirmed'
      AND o.amount_minor>0
  ) THEN RAISE(ABORT,'confirmed chain payment evidence required') END;
END;

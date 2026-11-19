-- Agent-controlled receiving identity and direct-payment invoice intents.
-- This migration does not create wallets, store private keys, verify chain payments,
-- credit balances, or enable public checkout.

CREATE TABLE IF NOT EXISTS financial_agent_receiving_wallets (
  wallet_id TEXT PRIMARY KEY,
  owner_id TEXT NOT NULL,
  agent_id TEXT NOT NULL,
  network TEXT NOT NULL CHECK (network = 'base-mainnet'),
  chain_id INTEGER NOT NULL CHECK (chain_id = 8453),
  asset_code TEXT NOT NULL CHECK (asset_code = 'USDC'),
  token_contract TEXT NOT NULL CHECK (lower(token_contract) = '0x833589fcd6ed6e08f4c7c32d4f71b54bda02913'),
  token_decimals INTEGER NOT NULL CHECK (token_decimals = 6),
  receiving_address TEXT NOT NULL CHECK (length(receiving_address) = 42 AND substr(receiving_address,1,2) = '0x'),
  status TEXT NOT NULL CHECK (status IN ('active','revoked')),
  signer_key_fingerprint TEXT NOT NULL,
  registration_payload_hash TEXT NOT NULL,
  registration_signature TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (owner_id) REFERENCES financial_participants(participant_id) ON DELETE RESTRICT,
  FOREIGN KEY (agent_id) REFERENCES financial_participants(participant_id) ON DELETE RESTRICT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_financial_agent_wallet_one_active_asset
  ON financial_agent_receiving_wallets(owner_id,agent_id,network,asset_code)
  WHERE status='active';
CREATE INDEX IF NOT EXISTS idx_financial_agent_wallet_lookup
  ON financial_agent_receiving_wallets(owner_id,agent_id,status);

CREATE TABLE IF NOT EXISTS financial_receiving_invoices (
  invoice_id TEXT PRIMARY KEY,
  owner_id TEXT NOT NULL,
  agent_id TEXT NOT NULL,
  wallet_id TEXT NOT NULL,
  order_id TEXT NOT NULL,
  amount_minor INTEGER NOT NULL CHECK (amount_minor > 0),
  asset_code TEXT NOT NULL CHECK (asset_code = 'USDC'),
  network TEXT NOT NULL CHECK (network = 'base-mainnet'),
  chain_id INTEGER NOT NULL CHECK (chain_id = 8453),
  token_contract TEXT NOT NULL CHECK (lower(token_contract) = '0x833589fcd6ed6e08f4c7c32d4f71b54bda02913'),
  receiving_address TEXT NOT NULL,
  payment_uri TEXT NOT NULL,
  description TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('awaiting_payment','expired','review','confirmed','reversed')),
  expires_at TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (owner_id) REFERENCES financial_participants(participant_id) ON DELETE RESTRICT,
  FOREIGN KEY (agent_id) REFERENCES financial_participants(participant_id) ON DELETE RESTRICT,
  FOREIGN KEY (wallet_id) REFERENCES financial_agent_receiving_wallets(wallet_id) ON DELETE RESTRICT,
  UNIQUE(owner_id,agent_id,order_id)
);

CREATE INDEX IF NOT EXISTS idx_financial_receiving_invoices_agent
  ON financial_receiving_invoices(owner_id,agent_id,status,created_at DESC);

CREATE TRIGGER IF NOT EXISTS trg_financial_receiving_wallet_no_delete
BEFORE DELETE ON financial_agent_receiving_wallets
BEGIN SELECT RAISE(ABORT,'receiving wallet history is retained'); END;

CREATE TRIGGER IF NOT EXISTS trg_financial_receiving_invoice_no_delete
BEFORE DELETE ON financial_receiving_invoices
BEGIN SELECT RAISE(ABORT,'receiving invoice history is retained'); END;

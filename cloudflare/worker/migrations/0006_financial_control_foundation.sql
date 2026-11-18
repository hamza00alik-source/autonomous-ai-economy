-- Cloud financial-control foundation.
-- Additive schema only: no rows are seeded, no local SQLite data is copied,
-- and no Worker route reads or writes these tables yet.

CREATE TABLE IF NOT EXISTS financial_participants (
  participant_id TEXT PRIMARY KEY,
  participant_type TEXT NOT NULL CHECK (participant_type IN ('owner','agent','operator')),
  status TEXT NOT NULL CHECK (status IN ('active','suspended','revoked')),
  operator_id TEXT,
  public_key_jwk TEXT,
  key_fingerprint TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  CHECK (
    (participant_type = 'agent' AND operator_id IS NOT NULL) OR
    (participant_type != 'agent' AND operator_id IS NULL)
  )
);

CREATE INDEX IF NOT EXISTS idx_financial_participants_status
  ON financial_participants(participant_type, status);

CREATE TABLE IF NOT EXISTS financial_accounts (
  account_id TEXT PRIMARY KEY,
  owner_id TEXT NOT NULL,
  agent_id TEXT,
  account_type TEXT NOT NULL CHECK (account_type IN (
    'treasury','agent_operating','owner_payable','reserve','fee_expense','operating_expense'
  )),
  currency TEXT NOT NULL CHECK (currency GLOB '[A-Z][A-Z][A-Z]'),
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','frozen','closed')),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (owner_id) REFERENCES financial_participants(participant_id) ON DELETE RESTRICT,
  FOREIGN KEY (agent_id) REFERENCES financial_participants(participant_id) ON DELETE RESTRICT,
  CHECK (
    (account_type = 'agent_operating' AND agent_id IS NOT NULL) OR
    (account_type != 'agent_operating' AND agent_id IS NULL)
  ),
  UNIQUE(owner_id, agent_id, account_type, currency)
);

CREATE INDEX IF NOT EXISTS idx_financial_accounts_owner
  ON financial_accounts(owner_id, status, currency);

CREATE TABLE IF NOT EXISTS financial_journal_transactions (
  transaction_id TEXT PRIMARY KEY,
  owner_id TEXT NOT NULL,
  idempotency_key TEXT NOT NULL UNIQUE,
  source_type TEXT NOT NULL CHECK (source_type IN (
    'settlement','allocation','expense','adjustment','reversal'
  )),
  source_reference TEXT NOT NULL,
  currency TEXT NOT NULL CHECK (currency GLOB '[A-Z][A-Z][A-Z]'),
  status TEXT NOT NULL CHECK (status = 'posted'),
  description TEXT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY (owner_id) REFERENCES financial_participants(participant_id) ON DELETE RESTRICT,
  UNIQUE(owner_id, source_type, source_reference, currency)
);

CREATE INDEX IF NOT EXISTS idx_financial_journal_owner_created
  ON financial_journal_transactions(owner_id, created_at DESC);

CREATE TABLE IF NOT EXISTS financial_journal_postings (
  transaction_id TEXT NOT NULL,
  line_number INTEGER NOT NULL CHECK (line_number > 0),
  account_id TEXT NOT NULL,
  direction TEXT NOT NULL CHECK (direction IN ('debit','credit')),
  amount_minor INTEGER NOT NULL CHECK (amount_minor > 0),
  currency TEXT NOT NULL CHECK (currency GLOB '[A-Z][A-Z][A-Z]'),
  created_at TEXT NOT NULL,
  PRIMARY KEY(transaction_id, line_number),
  FOREIGN KEY (transaction_id) REFERENCES financial_journal_transactions(transaction_id) ON DELETE RESTRICT,
  FOREIGN KEY (account_id) REFERENCES financial_accounts(account_id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_financial_postings_account
  ON financial_journal_postings(account_id, currency, transaction_id);

CREATE TABLE IF NOT EXISTS financial_settlement_receipts (
  receipt_id TEXT PRIMARY KEY,
  owner_id TEXT NOT NULL,
  agent_id TEXT NOT NULL,
  provider TEXT NOT NULL,
  provider_reference TEXT NOT NULL,
  gross_amount_minor INTEGER NOT NULL CHECK (gross_amount_minor > 0),
  fee_amount_minor INTEGER NOT NULL CHECK (fee_amount_minor >= 0 AND fee_amount_minor <= gross_amount_minor),
  currency TEXT NOT NULL CHECK (currency GLOB '[A-Z][A-Z][A-Z]'),
  status TEXT NOT NULL CHECK (status IN ('pending','confirmed','reconciled','reversed','review')),
  provider_event_reference TEXT,
  provider_evidence_hash TEXT,
  settled_at TEXT,
  reconciled_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (owner_id) REFERENCES financial_participants(participant_id) ON DELETE RESTRICT,
  FOREIGN KEY (agent_id) REFERENCES financial_participants(participant_id) ON DELETE RESTRICT,
  UNIQUE(provider, provider_reference)
);

CREATE INDEX IF NOT EXISTS idx_financial_receipts_agent_status
  ON financial_settlement_receipts(agent_id, status, created_at DESC);

CREATE TABLE IF NOT EXISTS financial_policies (
  policy_id TEXT NOT NULL,
  version INTEGER NOT NULL CHECK (version > 0),
  owner_id TEXT NOT NULL,
  agent_id TEXT NOT NULL,
  currency TEXT NOT NULL CHECK (currency GLOB '[A-Z][A-Z][A-Z]'),
  per_transaction_limit_minor INTEGER NOT NULL CHECK (per_transaction_limit_minor > 0),
  daily_spend_limit_minor INTEGER NOT NULL CHECK (daily_spend_limit_minor > 0),
  allowed_destinations_json TEXT NOT NULL,
  canonical_payload TEXT NOT NULL,
  signature_base64url TEXT NOT NULL,
  signer_key_fingerprint TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('active','superseded','revoked')),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY(policy_id, version),
  FOREIGN KEY (owner_id) REFERENCES financial_participants(participant_id) ON DELETE RESTRICT,
  FOREIGN KEY (agent_id) REFERENCES financial_participants(participant_id) ON DELETE RESTRICT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_financial_policy_one_active
  ON financial_policies(owner_id, agent_id, policy_id)
  WHERE status = 'active';

CREATE TABLE IF NOT EXISTS financial_budget_reservations (
  reservation_id TEXT PRIMARY KEY,
  owner_id TEXT NOT NULL,
  agent_id TEXT NOT NULL,
  policy_id TEXT NOT NULL,
  policy_version INTEGER NOT NULL CHECK (policy_version > 0),
  idempotency_key TEXT NOT NULL UNIQUE,
  destination TEXT NOT NULL,
  currency TEXT NOT NULL CHECK (currency GLOB '[A-Z][A-Z][A-Z]'),
  amount_minor INTEGER NOT NULL CHECK (amount_minor > 0),
  status TEXT NOT NULL CHECK (status IN ('reserved','settled','released','expired')),
  expires_at TEXT NOT NULL,
  settled_transaction_id TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (owner_id) REFERENCES financial_participants(participant_id) ON DELETE RESTRICT,
  FOREIGN KEY (agent_id) REFERENCES financial_participants(participant_id) ON DELETE RESTRICT,
  FOREIGN KEY (policy_id, policy_version) REFERENCES financial_policies(policy_id, version) ON DELETE RESTRICT,
  FOREIGN KEY (settled_transaction_id) REFERENCES financial_journal_transactions(transaction_id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_financial_reservations_agent_status
  ON financial_budget_reservations(agent_id, status, expires_at);

CREATE TABLE IF NOT EXISTS financial_expense_schedules (
  schedule_id TEXT PRIMARY KEY,
  owner_id TEXT NOT NULL,
  agent_id TEXT NOT NULL,
  policy_id TEXT NOT NULL,
  policy_version INTEGER NOT NULL CHECK (policy_version > 0),
  destination TEXT NOT NULL,
  currency TEXT NOT NULL CHECK (currency GLOB '[A-Z][A-Z][A-Z]'),
  amount_minor INTEGER NOT NULL CHECK (amount_minor > 0),
  interval_seconds INTEGER NOT NULL CHECK (interval_seconds BETWEEN 3600 AND 2678400),
  next_due_at TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('active','paused','cancelled','blocked')),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (owner_id) REFERENCES financial_participants(participant_id) ON DELETE RESTRICT,
  FOREIGN KEY (agent_id) REFERENCES financial_participants(participant_id) ON DELETE RESTRICT,
  FOREIGN KEY (policy_id, policy_version) REFERENCES financial_policies(policy_id, version) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_financial_schedules_due
  ON financial_expense_schedules(status, next_due_at);

CREATE TABLE IF NOT EXISTS financial_audit_events (
  event_id TEXT PRIMARY KEY,
  owner_id TEXT NOT NULL,
  actor_id TEXT NOT NULL,
  event_type TEXT NOT NULL,
  target_type TEXT NOT NULL,
  target_id TEXT NOT NULL,
  request_id TEXT,
  details_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY (owner_id) REFERENCES financial_participants(participant_id) ON DELETE RESTRICT,
  FOREIGN KEY (actor_id) REFERENCES financial_participants(participant_id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_financial_audit_owner_created
  ON financial_audit_events(owner_id, created_at DESC);

-- Posted journal history and audit events are append-only.
CREATE TRIGGER IF NOT EXISTS trg_financial_journal_transactions_no_update
BEFORE UPDATE ON financial_journal_transactions
BEGIN
  SELECT RAISE(ABORT, 'posted journal transactions are immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_financial_journal_transactions_no_delete
BEFORE DELETE ON financial_journal_transactions
BEGIN
  SELECT RAISE(ABORT, 'posted journal transactions are immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_financial_journal_postings_no_update
BEFORE UPDATE ON financial_journal_postings
BEGIN
  SELECT RAISE(ABORT, 'posted journal postings are immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_financial_journal_postings_no_delete
BEFORE DELETE ON financial_journal_postings
BEGIN
  SELECT RAISE(ABORT, 'posted journal postings are immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_financial_posting_currency_match
BEFORE INSERT ON financial_journal_postings
WHEN NOT EXISTS (
  SELECT 1
  FROM financial_journal_transactions t
  JOIN financial_accounts a ON a.account_id = NEW.account_id
  WHERE t.transaction_id = NEW.transaction_id
    AND t.currency = NEW.currency
    AND a.currency = NEW.currency
)
BEGIN
  SELECT RAISE(ABORT, 'posting currency must match transaction and account');
END;

CREATE TRIGGER IF NOT EXISTS trg_financial_audit_events_no_update
BEFORE UPDATE ON financial_audit_events
BEGIN
  SELECT RAISE(ABORT, 'financial audit events are append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_financial_audit_events_no_delete
BEFORE DELETE ON financial_audit_events
BEGIN
  SELECT RAISE(ABORT, 'financial audit events are append-only');
END;

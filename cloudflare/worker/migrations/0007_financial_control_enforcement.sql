-- Cloud financial controls: durable reservations, recurring occurrences and emergency pause.
-- Additive only. No owner is seeded and no financial activity is enabled.

CREATE TABLE IF NOT EXISTS financial_control_state (
  owner_id TEXT PRIMARY KEY,
  emergency_paused INTEGER NOT NULL DEFAULT 1 CHECK (emergency_paused IN (0,1)),
  pause_reason TEXT NOT NULL DEFAULT 'new cloud financial controls default to paused',
  changed_by TEXT,
  changed_at TEXT NOT NULL,
  FOREIGN KEY (owner_id) REFERENCES financial_participants(participant_id) ON DELETE RESTRICT,
  FOREIGN KEY (changed_by) REFERENCES financial_participants(participant_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS financial_expense_occurrences (
  occurrence_id TEXT PRIMARY KEY,
  schedule_id TEXT NOT NULL,
  owner_id TEXT NOT NULL,
  agent_id TEXT NOT NULL,
  policy_id TEXT NOT NULL,
  policy_version INTEGER NOT NULL,
  due_at TEXT NOT NULL,
  idempotency_key TEXT NOT NULL UNIQUE,
  reservation_id TEXT,
  status TEXT NOT NULL CHECK (status IN ('claimed','reserved','settled','blocked','skipped')),
  reason_code TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (schedule_id) REFERENCES financial_expense_schedules(schedule_id) ON DELETE RESTRICT,
  FOREIGN KEY (owner_id) REFERENCES financial_participants(participant_id) ON DELETE RESTRICT,
  FOREIGN KEY (agent_id) REFERENCES financial_participants(participant_id) ON DELETE RESTRICT,
  FOREIGN KEY (policy_id, policy_version) REFERENCES financial_policies(policy_id, version) ON DELETE RESTRICT,
  FOREIGN KEY (reservation_id) REFERENCES financial_budget_reservations(reservation_id) ON DELETE RESTRICT,
  UNIQUE(schedule_id, due_at)
);

CREATE INDEX IF NOT EXISTS idx_financial_occurrences_owner_created
  ON financial_expense_occurrences(owner_id, created_at DESC);

CREATE TRIGGER IF NOT EXISTS trg_financial_reservation_authorization
BEFORE INSERT ON financial_budget_reservations
BEGIN
  SELECT CASE WHEN NOT EXISTS (
    SELECT 1 FROM financial_policies p
    JOIN financial_participants o ON o.participant_id=p.owner_id
    JOIN financial_participants a ON a.participant_id=p.agent_id
    JOIN financial_participants s ON s.participant_id=p.signer_id
    WHERE p.policy_id=NEW.policy_id AND p.version=NEW.policy_version
      AND p.owner_id=NEW.owner_id AND p.agent_id=NEW.agent_id
      AND p.currency=NEW.currency AND p.status='active'
      AND NEW.amount_minor<=p.per_transaction_limit_minor
      AND EXISTS (SELECT 1 FROM json_each(p.allowed_destinations_json) d WHERE d.value=NEW.destination)
      AND o.status='active' AND a.status='active' AND s.status='active'
      AND o.participant_type='owner' AND a.participant_type='agent'
      AND s.participant_type='operator' AND s.owner_id=o.participant_id
      AND a.owner_id=o.participant_id AND a.operator_id=s.participant_id
  ) THEN RAISE(ABORT, 'reservation policy or participant authorization failed') END;

  SELECT CASE WHEN EXISTS (
    SELECT 1 FROM financial_control_state c
    WHERE c.owner_id=NEW.owner_id AND c.emergency_paused=1
  ) THEN RAISE(ABORT, 'owner emergency pause is active') END;

  SELECT CASE WHEN COALESCE((
    SELECT SUM(CASE WHEN j.direction='credit' THEN j.amount_minor ELSE -j.amount_minor END)
    FROM financial_accounts a
    LEFT JOIN financial_journal_postings j ON j.account_id=a.account_id AND j.currency=NEW.currency
    WHERE a.owner_id=NEW.owner_id AND a.agent_id=NEW.agent_id
      AND a.account_type='agent_operating' AND a.currency=NEW.currency AND a.status='active'
  ),0) - COALESCE((
    SELECT SUM(r.amount_minor) FROM financial_budget_reservations r
    WHERE r.owner_id=NEW.owner_id AND r.agent_id=NEW.agent_id AND r.currency=NEW.currency
      AND r.status='reserved' AND r.expires_at > strftime('%Y-%m-%dT%H:%M:%fZ','now')
  ),0) < NEW.amount_minor
  THEN RAISE(ABORT, 'insufficient available agent budget') END;

  SELECT CASE WHEN COALESCE((
    SELECT SUM(r.amount_minor) FROM financial_budget_reservations r
    WHERE r.owner_id=NEW.owner_id AND r.agent_id=NEW.agent_id AND r.currency=NEW.currency
      AND substr(r.created_at,1,10)=substr(NEW.created_at,1,10)
      AND (r.status='settled' OR (r.status='reserved' AND r.expires_at > strftime('%Y-%m-%dT%H:%M:%fZ','now')))
  ),0) + NEW.amount_minor > (
    SELECT p.daily_spend_limit_minor FROM financial_policies p
    WHERE p.policy_id=NEW.policy_id AND p.version=NEW.policy_version AND p.status='active'
  ) THEN RAISE(ABORT, 'daily spend limit exceeded') END;
END;

CREATE TRIGGER IF NOT EXISTS trg_financial_reservation_no_policy_bypass
BEFORE UPDATE OF status ON financial_budget_reservations
WHEN NEW.status='settled'
BEGIN
  SELECT CASE WHEN OLD.status!='reserved' THEN RAISE(ABORT, 'only reserved expenses can settle') END;
  SELECT CASE WHEN EXISTS (
    SELECT 1 FROM financial_control_state c WHERE c.owner_id=OLD.owner_id AND c.emergency_paused=1
  ) THEN RAISE(ABORT, 'owner emergency pause is active') END;
  SELECT CASE WHEN NOT EXISTS (
    SELECT 1 FROM financial_policies p
    WHERE p.policy_id=OLD.policy_id AND p.version=OLD.policy_version AND p.status='active'
      AND p.owner_id=OLD.owner_id AND p.agent_id=OLD.agent_id
      AND OLD.amount_minor<=p.per_transaction_limit_minor
      AND EXISTS (SELECT 1 FROM json_each(p.allowed_destinations_json) d WHERE d.value=OLD.destination)
  ) THEN RAISE(ABORT, 'signed policy is no longer active') END;
  SELECT CASE WHEN NOT EXISTS (
    SELECT 1 FROM financial_journal_transactions t
    WHERE t.transaction_id=NEW.settled_transaction_id
      AND t.owner_id=OLD.owner_id AND t.source_type='expense'
      AND t.source_reference=OLD.reservation_id AND t.currency=OLD.currency
  ) THEN RAISE(ABORT, 'settlement journal transaction is missing or mismatched') END;
END;

CREATE TRIGGER IF NOT EXISTS trg_financial_occurrence_authorization
BEFORE INSERT ON financial_expense_occurrences
BEGIN
  SELECT CASE WHEN NOT EXISTS (
    SELECT 1 FROM financial_expense_schedules s
    JOIN financial_policies p ON p.policy_id=s.policy_id AND p.version=s.policy_version
    WHERE s.schedule_id=NEW.schedule_id AND s.owner_id=NEW.owner_id AND s.agent_id=NEW.agent_id
      AND s.policy_id=NEW.policy_id AND s.policy_version=NEW.policy_version
      AND s.status='active' AND p.status='active'
      AND p.owner_id=NEW.owner_id AND p.agent_id=NEW.agent_id
      AND s.amount_minor<=p.per_transaction_limit_minor
      AND EXISTS (SELECT 1 FROM json_each(p.allowed_destinations_json) d WHERE d.value=s.destination)
  ) THEN RAISE(ABORT, 'recurring expense schedule is not authorized') END;
END;

CREATE TRIGGER IF NOT EXISTS trg_financial_control_state_audit
AFTER INSERT ON financial_control_state
BEGIN
  INSERT INTO financial_audit_events(event_id,owner_id,actor_id,event_type,target_type,target_id,request_id,details_json,created_at)
  SELECT lower(hex(randomblob(16))),NEW.owner_id,NEW.changed_by,'financial.emergency_pause_initialized',
    'financial_control_state',NEW.owner_id,NULL,
    json_object('emergency_paused',NEW.emergency_paused,'reason',NEW.pause_reason),NEW.changed_at
  WHERE NEW.changed_by IS NOT NULL;
END;

-- Emergency pause is fail-closed: absence of an owner control row is treated as paused by services.

CREATE TRIGGER IF NOT EXISTS trg_financial_reservation_requires_explicit_unpause
BEFORE INSERT ON financial_budget_reservations
WHEN NOT EXISTS (
  SELECT 1 FROM financial_control_state c
  WHERE c.owner_id=NEW.owner_id AND c.emergency_paused=0
)
BEGIN
  SELECT RAISE(ABORT, 'owner emergency pause is active or not configured');
END;

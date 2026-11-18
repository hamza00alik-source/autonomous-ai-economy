CREATE TABLE IF NOT EXISTS swarmmemo_work_items (
  task_id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  room TEXT,
  requester TEXT,
  task_text TEXT NOT NULL,
  reward_json TEXT NOT NULL,
  requester_record_json TEXT,
  deadline TEXT,
  board_state TEXT NOT NULL,
  eligible INTEGER NOT NULL DEFAULT 0 CHECK (eligible IN (0,1)),
  eligibility_reason TEXT,
  owner_approved INTEGER NOT NULL DEFAULT 0 CHECK (owner_approved IN (0,1)),
  execution_state TEXT NOT NULL DEFAULT 'awaiting_owner_approval'
    CHECK (execution_state IN ('awaiting_owner_approval','approved_awaiting_executor','executing','ready_for_review','submitted','accepted','rejected','expired','blocked')),
  result_text TEXT,
  result_message_id TEXT,
  claim_receipt_json TEXT,
  last_error TEXT,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_swarmmemo_work_state
  ON swarmmemo_work_items(board_state, execution_state, last_seen_at);
CREATE INDEX IF NOT EXISTS idx_swarmmemo_work_approval
  ON swarmmemo_work_items(owner_approved, execution_state, deadline);

CREATE TABLE IF NOT EXISTS swarmmemo_poll_state (
  source TEXT PRIMARY KEY,
  last_success_at TEXT,
  last_error TEXT,
  last_count INTEGER NOT NULL DEFAULT 0,
  last_http_status INTEGER,
  since_cursor TEXT,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS taskmarket_work_items (
 task_id TEXT PRIMARY KEY,
 title TEXT NOT NULL,
 description TEXT NOT NULL,
 chain_id INTEGER NOT NULL,
 mode TEXT NOT NULL,
 board_state TEXT NOT NULL,
 reward_base_units TEXT NOT NULL,
 reward_usdc TEXT,
 net_reward_base_units TEXT NOT NULL,
 net_reward_usdc TEXT,
 escrow_tx_hash TEXT,
 escrow_tracked INTEGER NOT NULL DEFAULT 0 CHECK (escrow_tracked IN (0,1)),
 escrow_booked_base_units TEXT,
 escrow_verified INTEGER NOT NULL DEFAULT 0 CHECK (escrow_verified IN (0,1)),
 escrow_verification_status TEXT NOT NULL DEFAULT 'not_checked',
 escrow_verified_amount_base_units TEXT,
 submission_count INTEGER NOT NULL DEFAULT 0,
 stake_required INTEGER NOT NULL DEFAULT 0 CHECK (stake_required IN (0,1)),
 stake_bps INTEGER NOT NULL DEFAULT 0,
 platform_fee_bps INTEGER NOT NULL DEFAULT 0,
 submission_window_open INTEGER NOT NULL DEFAULT 0 CHECK (submission_window_open IN (0,1)),
 expiry_time TEXT,
 requester TEXT,
 tags_json TEXT NOT NULL DEFAULT '[]',
 eligible INTEGER NOT NULL DEFAULT 0 CHECK (eligible IN (0,1)),
 eligibility_reasons_json TEXT NOT NULL DEFAULT '[]',
 owner_approved INTEGER NOT NULL DEFAULT 0 CHECK (owner_approved IN (0,1)),
 execution_state TEXT NOT NULL DEFAULT 'awaiting_owner_approval'
  CHECK (execution_state IN ('awaiting_owner_approval','approved_awaiting_executor','executing','ready_for_review','submitted','accepted','rejected','expired','blocked')),
 first_seen_at TEXT NOT NULL,
 last_seen_at TEXT NOT NULL,
 updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_taskmarket_work_approval
 ON taskmarket_work_items(owner_approved,execution_state,eligible,expiry_time);
CREATE INDEX IF NOT EXISTS idx_taskmarket_work_state
 ON taskmarket_work_items(board_state,eligible,last_seen_at);
CREATE TABLE IF NOT EXISTS taskmarket_poll_state (
 source TEXT PRIMARY KEY,
 last_success_at TEXT,
 last_error TEXT,
 last_count INTEGER NOT NULL DEFAULT 0,
 last_http_status INTEGER,
 updated_at TEXT NOT NULL
);

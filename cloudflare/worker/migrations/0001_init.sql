CREATE TABLE IF NOT EXISTS ai_tasks (
    task_id TEXT PRIMARY KEY,
    idempotency_key TEXT NOT NULL UNIQUE,
    task_type TEXT NOT NULL CHECK (task_type = 'product_copy'),
    status TEXT NOT NULL CHECK (status IN ('queued','running','completed','failed','blocked_budget','stalled')),
    payload_json TEXT NOT NULL,
    result_json TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    claimed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_ai_tasks_status_created
    ON ai_tasks(status, created_at, task_id);

CREATE TABLE IF NOT EXISTS ai_daily_budget (
    utc_day TEXT PRIMARY KEY,
    reserved_neurons INTEGER NOT NULL CHECK (reserved_neurons >= 0)
);

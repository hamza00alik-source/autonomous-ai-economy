ALTER TABLE crypto_payment_invoices
    ADD COLUMN agent_id TEXT NOT NULL DEFAULT 'unassigned';

CREATE TABLE IF NOT EXISTS agent_revenue_events (
    order_id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    product_id TEXT NOT NULL,
    gross_amount_minor INTEGER NOT NULL CHECK (gross_amount_minor > 0),
    gross_currency TEXT NOT NULL CHECK (gross_currency = 'usd'),
    provider_payment_id TEXT NOT NULL,
    crypto_received_amount TEXT,
    crypto_currency TEXT,
    provider_outcome_amount TEXT,
    provider_outcome_currency TEXT,
    status TEXT NOT NULL CHECK (status IN (
        'settled_pending_reconciliation','reconciled','refund_review','reversed'
    )),
    net_amount_minor INTEGER,
    net_currency TEXT,
    agent_credit_minor INTEGER,
    agent_credit_currency TEXT,
    settled_at TEXT NOT NULL,
    reconciled_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (order_id) REFERENCES crypto_payment_invoices(order_id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_agent_revenue_agent_status
    ON agent_revenue_events(agent_id, status, settled_at);

-- Base-native USDC checkout ledger. This migration creates dormant records only;
-- the Worker routes and public checkout remain disabled until reviewed configuration exists.

CREATE TABLE IF NOT EXISTS base_usdc_invoices (
    order_id TEXT PRIMARY KEY,
    order_id_hash TEXT NOT NULL UNIQUE,
    product_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    amount_minor INTEGER NOT NULL CHECK (amount_minor > 0),
    gross_amount_minor INTEGER NOT NULL CHECK (gross_amount_minor > 0),
    merchant_address TEXT NOT NULL,
    invoice_signature TEXT NOT NULL,
    invoice_deadline INTEGER NOT NULL,
    buyer_token_hash TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN (
        'pending','settled','expired','review','refunded'
    )),
    buyer_address TEXT,
    transaction_hash TEXT UNIQUE,
    log_index INTEGER,
    block_number INTEGER,
    block_hash TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    settled_at TEXT,
    download_expires_at TEXT,
    download_count INTEGER NOT NULL DEFAULT 0 CHECK (download_count >= 0)
);

CREATE INDEX IF NOT EXISTS idx_base_usdc_invoice_status
    ON base_usdc_invoices(status, created_at);

CREATE TABLE IF NOT EXISTS base_usdc_payment_events (
    chain_id INTEGER NOT NULL CHECK (chain_id = 8453),
    transaction_hash TEXT NOT NULL,
    log_index INTEGER NOT NULL CHECK (log_index >= 0),
    order_id TEXT NOT NULL,
    buyer_address TEXT NOT NULL,
    merchant_address TEXT NOT NULL,
    token_address TEXT NOT NULL,
    amount_minor INTEGER NOT NULL CHECK (amount_minor > 0),
    block_number INTEGER NOT NULL,
    block_hash TEXT NOT NULL,
    transaction_status TEXT NOT NULL CHECK (transaction_status IN ('confirmed','orphaned','quarantined')),
    observed_at TEXT NOT NULL,
    PRIMARY KEY (chain_id, transaction_hash, log_index)
);

CREATE INDEX IF NOT EXISTS idx_base_usdc_events_order
    ON base_usdc_payment_events(order_id, observed_at);

CREATE TABLE IF NOT EXISTS base_usdc_indexer_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    next_block INTEGER NOT NULL CHECK (next_block >= 0),
    last_block_hash TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS base_usdc_quarantine (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    transaction_hash TEXT NOT NULL,
    log_index INTEGER NOT NULL,
    reason TEXT NOT NULL,
    event_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(transaction_hash, log_index)
);


CREATE TABLE IF NOT EXISTS base_usdc_agent_revenue_events (
    order_id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    product_id TEXT NOT NULL,
    gross_amount_minor INTEGER NOT NULL CHECK (gross_amount_minor > 0),
    gross_currency TEXT NOT NULL CHECK (gross_currency = 'usd'),
    transaction_hash TEXT NOT NULL UNIQUE,
    crypto_received_amount TEXT NOT NULL,
    crypto_currency TEXT NOT NULL CHECK (crypto_currency = 'USDC'),
    status TEXT NOT NULL CHECK (status IN (
        'settled_pending_reconciliation','reconciled','refund_review','reversed'
    )),
    net_amount_minor INTEGER,
    agent_credit_minor INTEGER,
    settled_at TEXT NOT NULL,
    reconciled_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (order_id) REFERENCES base_usdc_invoices(order_id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_base_usdc_agent_revenue
    ON base_usdc_agent_revenue_events(agent_id, status, settled_at);

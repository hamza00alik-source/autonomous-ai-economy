CREATE TABLE IF NOT EXISTS crypto_payment_invoices (
    order_id TEXT PRIMARY KEY,
    provider TEXT NOT NULL CHECK (provider = 'nowpayments'),
    invoice_id TEXT UNIQUE,
    checkout_url TEXT,
    price_amount TEXT NOT NULL,
    price_currency TEXT NOT NULL CHECK (price_currency = 'usd'),
    status TEXT NOT NULL CHECK (status IN (
        'creating','pending','processing','underpaid','settled',
        'failed','expired','refunded','review','create_failed','create_uncertain'
    )),
    last_payment_id TEXT,
    actually_paid TEXT,
    pay_currency TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_crypto_payment_status_updated
    ON crypto_payment_invoices(status, updated_at);

CREATE TABLE IF NOT EXISTS crypto_payment_events (
    event_hash TEXT PRIMARY KEY,
    order_id TEXT NOT NULL,
    invoice_id TEXT,
    payment_id TEXT,
    provider_status TEXT NOT NULL,
    normalized_status TEXT NOT NULL,
    received_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_crypto_payment_events_order
    ON crypto_payment_events(order_id, received_at);

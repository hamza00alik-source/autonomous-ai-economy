ALTER TABLE crypto_payment_invoices
    ADD COLUMN product_id TEXT NOT NULL DEFAULT 'manual';

ALTER TABLE crypto_payment_invoices
    ADD COLUMN buyer_token_hash TEXT;

ALTER TABLE crypto_payment_invoices
    ADD COLUMN download_expires_at TEXT;

ALTER TABLE crypto_payment_invoices
    ADD COLUMN download_count INTEGER NOT NULL DEFAULT 0 CHECK (download_count >= 0);

CREATE INDEX IF NOT EXISTS idx_crypto_payment_product_status
    ON crypto_payment_invoices(product_id, status);

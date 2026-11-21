ALTER TABLE swarmmemo_identity_state ADD COLUMN credentials_ciphertext TEXT;
ALTER TABLE swarmmemo_identity_state ADD COLUMN credentials_salt TEXT;
ALTER TABLE swarmmemo_identity_state ADD COLUMN credentials_iv TEXT;

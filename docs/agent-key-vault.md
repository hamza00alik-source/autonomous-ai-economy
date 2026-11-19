# Agent Signing-Key Vault

## Storage model

The Cloudflare workerd runtime does not support structured-cloning a Web Crypto `CryptoKey` into Durable Object storage. The vault therefore never stores a CryptoKey object directly.

At identity creation:
1. Generate an Ed25519 key pair in memory.
2. Export the private key as PKCS#8 only long enough to encrypt it.
3. Derive a per-Durable-Object, per-agent AES-256-GCM wrapping key from the out-of-band `AAE_AGENT_KEY_ENCRYPTION_SECRET` using HKDF-SHA-256, a fresh random salt, and the Durable Object ID plus agent ID as context.
4. Store only the authenticated ciphertext, salt, IV, public JWK, fingerprint and creation time in Durable Object storage.
5. Discard the temporary extractable key pair from application state.

For signing, decrypt the PKCS#8 bytes in memory and import the private key as non-extractable. The private key is never returned from the Durable Object and the API only signs the narrowly scoped receiving-invoice request.

AES-GCM authenticates the encrypted record and its agent-specific additional data. A different Durable Object ID, wrong secret, altered ciphertext, or altered agent ID must fail closed.

## Required production configuration

Before any production identity bootstrap, an owner/operator must provision a newly generated, high-entropy secret (at least 32 bytes) as the Cloudflare Worker secret named:

`AAE_AGENT_KEY_ENCRYPTION_SECRET`

Use the Cloudflare dashboard's Worker settings / Secrets interface. Do not put the value in GitHub, Wrangler vars, source files, chat, screenshots, logs, or ordinary configuration. The test-only Wrangler configuration contains a fake CI value and must never be reused in production.

The secret is a key-encryption key. Rotating it without a planned re-encryption migration will make existing encrypted agent keys unreadable. Back up and rotate only under a reviewed recovery procedure. If the secret is lost, the encrypted private keys cannot be recovered.

## Validation and limitations

- Unit tests verify restart recovery, valid Ed25519 signatures, exact invoice scope, Durable Object binding, authenticated-ciphertext tamper rejection, and fail-closed behavior when the secret is missing.
- Cloudflare Workers runtime tests verify key persistence across Durable Object eviction and isolation between Durable Objects.
- These tests do not prove production secret provisioning, production deployment, backup/restore, or key rotation.
- This is an API request-signing key, not a blockchain wallet key. It does not authorize wallet transfers or treasury spending.

# AAE-owned SwarmMemo worker identity

The AAE worker creates and uses its own hosted SwarmMemo identity. The identity is separate from the owner's personal account.

## One-time secret configuration

Before the worker creates a hosted identity, configure a dedicated Cloudflare Worker secret:

- Name: `AAE_IDENTITY_ENCRYPTION_KEY`
- Value: a cryptographically random secret of at least 32 characters (prefer 64 or more).
- Scope: only the `autonomous-ai-economy-private-worker` Worker.
- Do not reuse `AAE_QUEUE_TOKEN`, wallet material, passwords, or any other account credential.
- Never put the value in GitHub, source files, D1 plaintext columns, issue comments, or ChatGPT messages.

In Cloudflare Dashboard, open **Workers & Pages → autonomous-ai-economy-private-worker → Settings → Variables and Secrets → Add → Secret**. Enter the name and secret value, then save. Generate the value with a password manager's cryptographically secure random-password generator. Do not share the value in chat.

## What the worker does

On its five-minute scheduled run, the worker:

1. Checks for the dedicated encryption secret before making any remote identity-creation request.
2. Creates one SwarmMemo hosted identity through the full MCP endpoint.
3. Encrypts the identity MCP URL and recovery code with AES-256-GCM. The key is derived using HKDF-SHA-256 from the dedicated secret and a per-record random salt.
4. Stores only ciphertext, salt and IV in D1. The status endpoint exposes identity metadata and non-secret error codes, never the URL token or recovery code.
5. Tests that the identity MCP endpoint exposes the required paid-work tools before any claim or submission is attempted.

A failed bootstrap caused solely by a missing/weak encryption secret can safely retry after the secret is configured. An uncertain remote creation is not retried automatically, to avoid creating duplicate identities.

## Rotation and recovery

Changing `AAE_IDENTITY_ENCRYPTION_KEY` without first re-encrypting the stored identity makes the ciphertext unreadable. Do not rotate or delete the secret casually. A controlled rotation must decrypt with the old key, re-encrypt with the new key, verify the ciphertext, and only then replace the old secret. Keep any recovery material in the platform's own secure recovery mechanism; never paste it into an issue or chat.

## Financial and work boundaries

Identity bootstrap does not claim tasks, post replies, submit deliverables, name a payout address, or move funds. Those actions are separate steps and must be verified independently. Only actual USDC received on Base counts as earned revenue.

# Agent receiving wallets and direct payment requests

## What this milestone does

Each enrolled agent can be assigned one owner-authorized public receiving address for Base mainnet USDC. The authenticated AAE service can create an idempotent, expiring payment request for an agent. Agents can be registered with a dedicated Ed25519 API public key. The owner authorizes the canonical key-registration payload and the agent proves possession of the matching private key. The private key is generated and retained by the agent runtime, never stored in D1. The signed invoice endpoint accepts method/path/timestamp/nonce/body-hash signatures and rejects requests outside a five-minute clock window and reused nonces. Each request is scoped to the path agent and its owner. Owner-authorized key revocation is supported; a revoked fingerprint cannot be re-registered. The legacy owner-authenticated invoice route remains available for compatibility.

Supported asset:
- Network: Base mainnet (chain ID 8453)
- Asset: native Circle USDC on Base
- Token contract: `0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913`
- Precision: 6 decimals

An owner signs the canonical receiving-wallet registration payload with the enrolled Ed25519 key. Only the public address, signature, and public metadata are stored. No private key, seed phrase, recovery phrase, or signing secret is accepted.


### Agent key enrollment and request signing

1. The agent runtime generates an Ed25519 key pair. The private key must remain in a protected runtime secret store and must never be sent to the Worker, D1, an LLM prompt, or a log.
2. The owner signs this canonical JSON payload (keys sorted recursively):
   `{"version":1,"owner_id":"...","agent_id":"...","public_key_jwk":{"crv":"Ed25519","kty":"OKP","x":"..."}}`
   The JWK must contain public material only.
3. The agent proves possession by signing UTF-8 text `AAE-AGENT-KEY-PROOF:v1:<sha256-of-canonical-public-jwk-json>`. Send the public JWK, owner signature and proof signature to `POST /v1/owner/agents/{agent_id}/api-key` using owner authentication.
4. For each signed invoice request, sign UTF-8 text consisting of five newline-separated fields: uppercase HTTP method, URL pathname, Unix timestamp in milliseconds, a fresh random base64url nonce (at least 16 characters), and lowercase hex SHA-256 of the exact raw request body.
5. Send headers `X-AAE-Key` (key fingerprint), `X-AAE-Timestamp`, `X-AAE-Nonce`, and `X-AAE-Signature` (base64url Ed25519 signature) to `POST /v1/agents/{agent_id}/receiving-invoices`.

The registration payload owner signature uses the owner's enrolled Ed25519 key. Key revocation requires an owner signature over canonical JSON:
`{"action":"revoke_agent_api_key","agent_id":"...","key_id":"...","owner_id":"...","version":1}`
submitted to `POST /v1/owner/agents/{agent_id}/api-key/{key_id}/revoke`.

This is a scoped authentication capability, not wallet custody or spending authority. The API currently permits invoice creation only. Key provisioning into an always-on agent runtime, encrypted-at-rest storage, backup/recovery, automated rotation UX, request-rate limiting and operational monitoring remain necessary before production use.


### Agent runtime signing client and $1 invoice example

`cloudflare/worker/src/agent_api_client.js` provides agent-side Ed25519 key generation and request signing:
- Generates a non-exportable private `CryptoKey`; only its public JWK is exported.
- Produces the owner-authorized enrollment envelope and agent proof-of-possession.
- Signs the exact raw request body, method, path, timestamp and unique nonce.
- Returns the headers required by the agent invoice API.

The helper is a client library, not an always-on agent runtime or a persistent key vault. The calling runtime must persist the non-exportable key in an appropriate protected keystore (for example, a supported platform keystore/secure CryptoKey store), implement backup/recovery and rotation, and never expose key material to the model. No key has been provisioned to a live agent in this change.

**Illustrative $1.00 USDC invoice preview (not a live invoice):**
- Amount: `1.00 USDC`
- Base USDC integer amount: `1000000` (six decimals)
- Network: `Base mainnet` (chain ID `8453`)
- Example-only recipient: `0x1111111111111111111111111111111111111111`
- Example payment URI: `ethereum:0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913@8453/transfer?address=0x1111111111111111111111111111111111111111&uint256=1000000`

The example address is a test placeholder and must not be paid. No invoice was created, no payment was requested, and no funds were received. A real invoice requires a verified agent, owner-authorized receiving address, live service configuration and an independently confirmed on-chain transfer.

## Payment request and chain verification

Creating an invoice creates a payment instruction only. It does not prove that a buyer paid. The invoice remains `awaiting_payment` until an owner-authenticated verification request checks the transaction against a configured HTTPS Base JSON-RPC endpoint.

The verifier checks:
- Base mainnet chain ID 8453 and successful transaction receipt.
- The exact native USDC contract and ERC-20 Transfer event.
- The invoice receiving address and exact six-decimal amount.
- Receipt block hash and number against the canonical block.
- The RPC endpoint's `finalized` block has reached the receipt block.
- Payment timestamp is before invoice expiry.

Exact, timely, finalized payments become `confirmed`. Underpayments, overpayments, and late payments are retained as immutable evidence with status `review`. Failed, missing, wrong-chain, non-finalized, or noncanonical transactions are not confirmed. A transaction hash can be bound to only one invoice.

The verifier uses one configured RPC endpoint (`BASE_RPC_URL`). This is stronger than trusting a buyer screenshot or callback, but it is not a trustless multi-provider oracle. Production should use independently operated RPC sources and monitoring.

## Asset-aware receipt journal

A separate asset-aware journal now supports Base USDC without mislabeling it as USD. Once an invoice has an exact confirmed chain observation, the service posts a balanced, idempotent journal transaction:
- Debit: agent pending-custody account associated with the receiving address.
- Credit: agent pending-revenue account.

The owner dashboard exposes this amount as **Pending wallet control**. This is a record of confirmed token transfers to the registered address; it is not a spendable agent balance. The existing USD simulated-spending policy, reservations and scheduler are not silently reused for USDC.

The journal will not post from an invoice status alone: the database requires immutable, confirmed chain-observation evidence. Journal transactions and postings are append-only. Duplicate verification attempts reuse the same idempotent journal entry.

## Wallet control and remaining autonomy

The owner-authorized address registry does not prove that the AI controls the receiving wallet. A public address is not a private signing capability. The AI never receives the private key.

Still required before the agent can independently use received funds:
1. Prove wallet control or provision an agent-owned smart account through a suitable restricted signer.
2. Provision the agent key securely in its runtime and rotate/revoke it through owner authorization; the signed API scope currently covers only creation of that agent's receiving invoices.
3. Add owner-signed USDC allocation/spending policies and asset-aware reservations and limits.
4. Execute transfers through a restricted signer or smart account, with on-chain transaction verification and replay protection.
5. Complete Pakistan legal/provider eligibility review before live commercial activation.

No USDC is currently marked available or spendable, no budget is funded, no product is automatically delivered, and no outgoing transfer is implemented.

## Activation boundary

This code is not deployed. The existing production Worker and D1 database are unchanged. No live checkout is enabled and no payment provider account is created. Owner/operator enrollment, migrations, wallet registration, RPC configuration, legal review, and production approval remain separate gates.


### Persistent agent API signing vault (implementation preview)

The follow-on branch adds `AgentKeyVault`, a SQLite-backed Durable Object configured as one deterministic vault per agent. It stores the non-exportable Ed25519 private `CryptoKey` in that object's private structured-clone storage and returns only the public JWK/fingerprint. It can produce the agent proof-of-possession and signs only the exact `POST /v1/agents/{agent_id}/receiving-invoices` request shape; it is not a general-purpose signing oracle.

Important boundaries:
- The Durable Object binding and class migration are code/configuration only. They have **not** been deployed and no production namespace or storage was created.
- Tests exercise restart behavior using Node's structured-clone implementation. A Cloudflare runtime integration test is still required to verify CryptoKey persistence in the actual Durable Objects runtime before any production use.
- The Worker has not yet been wired to provision or call the vault, and no live agent key has been enrolled.
- This is an API-authentication key, not a Base wallet key. It cannot sign blockchain transactions or move USDC.
- A Durable Object is persistent state, not an always-running agent process. Scheduling, model execution, task orchestration, owner approval, monitoring, and disaster recovery remain separate work.
- Before deployment, review Cloudflare access controls, backup/PITR implications for key material, key rotation/revocation, restore procedures, and account spending limits. Never expose the vault RPC methods to an unauthenticated public route.

# AAE Agent Wallet Architecture

Status: **W1 implementation under validation; W2 read-only observer implemented behind an injected RPC interface. No wallet keys generated, no chain endpoint configured, no funds moved.**

## Goal

Give each AAE agent a distinct blockchain wallet identity without requiring the owner to manually create an account at a wallet provider or approve every routine wallet operation. Wallet generation must be local to AAE and must not depend on a hosted wallet API.

This is not a claim that AAE or its agents are exempt from identity, licensing, sanctions, AML/CFT, tax, or other legal obligations. Provider or regulator requirements still apply to the actual business activity and jurisdiction.

## Two wallet types

### 1. Self-custody EVM account (first implementation target)

- Generate a fresh secp256k1 private key using a cryptographically secure random source.
- Derive the Ethereum-compatible public key and address locally.
- Never send the private key to a hosted wallet API, model prompt, log, telemetry, or user-visible response.
- Encrypt the private key at rest using authenticated encryption and a separately provisioned high-entropy secret; bind ciphertext to the agent ID and key version.
- Return only public address, chain-family metadata, key fingerprint, and creation metadata from normal APIs.
- Decrypt only inside a narrowly scoped signer process after agent authorization and policy checks.
- Support export/recovery only through a separate owner-controlled offline recovery procedure; never expose seed phrases in chat.

Wallet creation itself requires no blockchain RPC, wallet-provider account, API key, KYC, gas, or deployment. It creates a valid key/address pair locally; it does not create funds or prove that a wallet has been funded.

### 2. Smart-contract wallet (later implementation)

- Deploy or use a deterministic counterfactual smart account on a selected EVM chain.
- Agent authorization is represented by a signer key or policy module, not by an unrestricted model prompt.
- Enforce per-transaction and daily limits, token/chain allowlists, recipient allowlists, replay protection, and emergency pause/revocation.
- Smart-account deployment and transactions require chain access and gas (or a supported paymaster). A counterfactual address can be derived before deployment, but it is not yet an on-chain deployed contract.
- Use audited account implementations and independently review any custom contracts; do not invent a bespoke wallet contract for production.

## Relationship to existing AAE signing vault

The existing AgentKeyVault work stores Ed25519 API-authentication keys for AAE service requests. Those keys are **not** EVM wallet keys and must not be reused for blockchain signing. The existing API-key enrollment path includes owner authorization; that requirement must not be silently removed or bypassed.

The EVM wallet subsystem is a separate key domain, with separate key type, encryption context, authorization policy, audit events, and rotation/recovery lifecycle.

## Autonomy and approval policy

Routine agent activity can be autonomous within pre-approved policy limits. AAE must not require owner approval for every wallet creation or every permitted low-risk transaction. The following remain gated:
- Initial production activation and any legal/provider onboarding.
- Funding wallets or moving owner/treasury funds.
- Changing policy limits, allowlists, signer sets, or recovery configuration.
- High-value, unusual, cross-chain, or policy-exception transfers.
- Any custody or payment service offered to third parties where authorization is required.

A public address can receive unsolicited on-chain transfers without a provider API, but AAE must not treat an incoming transfer as accepted customer revenue until chain, token contract, destination, amount, finality, uniqueness, source/risk screening, and accounting classification have been verified. Incoming tokens can be counterfeit, unsupported, sanctioned, or otherwise unsafe.

## Network connectivity without a wallet API

AAE can avoid a hosted wallet-provider API. It still needs blockchain data access to discover and verify incoming transfers and broadcast outgoing transactions:
1. Preferred independence path: operate and maintain an appropriate node for the chosen chain.
2. Alternative: use a public RPC endpoint without an API key where available; availability, rate limits, privacy, and reliability are not guaranteed.

A wallet key can be generated offline. Sending a transaction cannot happen offline; it needs a signed transaction broadcast to the network and enough native gas token (unless an eligible paymaster covers gas).

## Phased delivery

### W0 — security and dependency review
- Select the EVM cryptography implementation and pin supported versions.
- Review existing vault implementation and decide whether the signer runs in Cloudflare Workers, a private runtime, or a dedicated isolated process.
- Threat-model key creation, encryption, access, backup, rotation, revocation, logs, crash dumps, and recovery.
- No production secrets or keys.

### W1 — local EVM wallet factory (test-only)
- Create an agent wallet record and generate an EVM key/address locally.
- Persist only authenticated ciphertext and public metadata.
- Enforce one wallet identity per agent per key domain/network family; idempotent creation.
- Tests for address derivation, entropy failure, ciphertext tampering, wrong agent binding, duplicate requests, and absence of private-key leakage.
- No RPC, chain interaction, funding, signing endpoint, or transfers in this phase.

### W2 — read-only chain observer
- The new observer verifies configured EVM chain ID, ERC-20 token contract, recipient, exact raw token amount, successful receipt, confirmation threshold, canonical block hash, and unique (chain_id, transaction_hash, log_index).
- The RPC transport is injected; the observer only invokes eth_chainId, eth_getTransactionReceipt, eth_blockNumber, and eth_getBlockByNumber.
- Amounts are integer token base units. Token decimals and human-readable formatting must come from separately verified token metadata; floats are not accepted.
- The observer has no private-key access, signing, transaction submission, broadcasting, or wallet funding capability.
- This is an adapter core, not a connected node. No chain has been selected and no live RPC endpoint, token contract, or production address is configured.
- A verified transfer record is not proof of legitimate customer revenue. Source/risk screening, accounting classification, and business/legal acceptance remain separate controls.

### W3 — bounded testnet signer
- Separate signer from observer.
- Enforce agent policy and spending limits before signing.
- Testnet only; no mainnet keys or funds.
- Exercise replay, nonce, fee, chain mismatch, malicious recipient, and policy-bypass tests.

### W4 — smart accounts
- Evaluate audited account abstraction implementations and deterministic deployment.
- Deploy only to testnet initially.
- Test owner/agent recovery, key rotation, daily limits, allowlists, pause, and account upgrades.

### W5 — real-network readiness review
- Separate legal, security, operational, accounting, and chain-specific approval.
- Mainnet activation, wallet funding, and real transfers remain disabled until explicit approval.

## Definition of done for W1

- A test can create an agent's EVM address without network access or an external wallet API.
- No private key or seed phrase appears in returned objects, logs, test output, or chat.
- Stored key material is authenticated-encrypted and agent-bound.
- Duplicate creation is idempotent; an existing agent cannot be rebound to another key record.
- Tampering and missing/incorrect encryption secret fail closed.
- Tests prove address derivation against independent known vectors.
- W1 has no transfer, signing, RPC, token, checkout, custody-for-customers, or production capability.

## Explicit non-goals

- No bypass of KYC, sanctions, AML/CFT, licensing, or provider controls.
- No fake internal credits represented as cryptocurrency.
- No automatic funding, sweeping, forwarding, refunds, payouts, or treasury transfers.
- No production wallet deployment or real-money activity in this PR.

# Treasury and Financial Controls

## Phase 1: simulation only

The current local append-only ledger is a prototype. It does not hold funds, connect to a bank, or submit blockchain transactions. The private Worker now records gross settled product receipts against the internal `game-asset-builder` producer ID, but net proceeds and agent credits remain null until actual wallet receipt, fees, refunds, taxes and owner-approved allocation are reconciled. See [agent revenue accounting](agent-revenue-accounting.md).

## Ownership

The human owner retains legal ownership and control of treasury assets. Agents are authorized operators only; they do not acquire equity or ownership by performing work.

## Future real-money prerequisites

Before enabling any live payment adapter:

- Written owner approval for the provider, asset, network, and use case.
- Legal and tax review for the operating jurisdiction.
- Provider eligibility and any required KYC/AML checks completed honestly.
- Owner-controlled key custody or a hardened signer with narrowly scoped permissions.
- Allowlisted destinations, transaction limits, rate limits, and emergency pause.
- Dual control for material transfers where feasible.
- Immutable audit records, reconciliation, and incident-response procedure.
- Tested recovery and key-rotation procedures.

## Prohibited by default

- Bypassing KYC, sanctions screening, or legal restrictions.
- Autonomous borrowing, leverage, or speculative trading.
- Unlimited spending or transfers.
- Agent access to seed phrases or unrestricted private keys.
- Mixing owner funds with customer funds.
- Representing simulated balances as actual revenue.

## Profit calculation

Only realized receipts count as revenue. Net profit must deduct refunds, fees, taxes, operating costs, and required reserves. Owner distributions occur only under an owner-approved policy after reconciliation. No illustrative allocation is a promise of returns.

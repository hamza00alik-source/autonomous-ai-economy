
# Agent revenue attribution and reconciliation

The first storefront product is assigned to the internal producer agent ID `game-asset-builder`. The deterministic procedural asset-builder agent creates the ZIP that the Worker deployment workflow packages for protected delivery.

When the NOWPayments callback is verified and the full invoice is marked `settled`, the Worker inserts one idempotent row in D1 `agent_revenue_events`:

- Agent and product IDs
- Gross order amount in USD minor units
- Provider payment ID
- Crypto amount/currency reported by the provider
- Provider outcome amount/currency when included in the callback
- Settlement time and reconciliation state

The owner-only endpoint `GET /v1/agents/game-asset-builder/revenue` returns aggregate totals and up to 50 recent events. Buyer identity and access tokens are not included.

**Accounting boundary:** a provider's `finished` callback is evidence of provider-reported settlement, not proof that the merchant's wallet received the expected net amount. Every new event starts as `settled_pending_reconciliation`. `net_amount_minor` and `agent_credit_minor` remain null until actual wallet receipt, provider/network fees, refunds, taxes and the owner-approved allocation are reconciled. A refund reverses an unreconciled event; a refund after reconciliation moves it to `refund_review`.

`game-asset-builder` is currently an internal producer identifier, not a cryptographic participant identity, legal person, company, or wallet owner. The merchant account and payout wallet remain under the owner's lawful control. No funds are automatically transferred to an agent. The local agent identity/key enrollment and a governed, non-custodial agent earnings/treasury design remain separate work.

This is an accounting bridge for the first product pilot, not a claim of revenue. No real buyer, settled payment, wallet receipt, reconciled net proceeds or agent credit exists yet.

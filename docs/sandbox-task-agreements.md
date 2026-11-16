# Sandbox Task Agreements

## Implemented local prototype

- A buyer creates a signed task offer against an active provider service listing.
- The offer binds buyer, provider, listing, task ID, scope, acceptance criteria, optional due date and optional quoted price/currency.
- The provider can accept or decline with a signature over the exact offer digest.
- The buyer can withdraw an offer before provider acceptance with a signed request.
- Task agreement events record offer, response and withdrawal.
- When the task-agreement table is present, work receipt submission must match an accepted agreement and the exact buyer/provider pair.

## Signing

Use `TaskAgreementStore.offer_signing_bytes(...)` to generate the exact canonical bytes for the buyer's Ed25519 signature. After the offer is recorded, the provider can use `response_signing_bytes(task_id, provider_id, "accept")` or `response_signing_bytes(..., "decline")` to obtain the response bytes. Buyer withdrawal uses `withdrawal_signing_bytes(task_id, buyer_id)`.

The task ID becomes the stable link between the accepted offer, work receipt, dispute record and reputation history.

## Important boundaries

- This is a sandbox task agreement record, not legal advice or a legally reviewed contract template.
- No payment is collected, reserved, escrowed, or transferred. A quoted price is informational only.
- No automated customer contact, deadline enforcement, refunds, penalties, cancellation fees or settlement is enabled.
- Both parties must have active participant records and bound signing keys. Key possession does not establish legal identity or authority to contract.
- A task offer can be withdrawn only before provider acceptance. Post-acceptance changes require a future explicit amendment protocol.
- The current local prototype has no remote API, access-control console or independent legal review.

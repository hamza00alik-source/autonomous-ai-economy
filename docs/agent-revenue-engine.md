# Agent Revenue Engine

Status: **cross-marketplace opportunity federation implemented in a draft branch; no external task is claimed and no revenue is earned by this feature.**

## Why this exists

AAE already had separate read-only adapters for BasedAgents, Jobbi and Taskmarket. This feature combines them into one durable shortlist so the economy can compare opportunities instead of treating each marketplace as a separate bot.

The engine ranks candidates using:
- task-scope/capability evaluation from the existing source adapter;
- source-reported payment and escrow state;
- independent Base receipt verification where the Taskmarket adapter supports it;
- gross and explicitly reported net reward;
- competition and task restrictions already checked by the source evaluator.

## Evidence tiers

- **ready_for_owner_review**: Taskmarket task scope passes its evaluator and the escrow-funding event independently verifies on Base. This is not permission to claim the task.
- **needs_owner_review**: source metadata, payout grade, or scope is promising but a required independent source/escrow check is unavailable or incomplete.
- No candidate is marked as paid revenue. Escrow funding is not worker earnings.

The current BasedAgents adapter has no independent chain receipt verifier, so the engine never treats its reported payment audit as sufficient proof of escrow. Jobbi is an index rather than the payer; its payout grade and escrow flag remain source claims until checked at the original board.

## Commands

After installing the package:

```bash
economy-revenue scan --limit 50 --verify-limit 25
economy-revenue list --limit 50
economy-revenue list --ready-only
```

The scanner is read-only. It does not register accounts, create wallets, claim work, submit deliverables, publish offers, contact customers, sign transactions, or transfer funds.

## What is required before autonomous earning

1. Owner review of the specific task and source-board terms.
2. A permitted agent identity and payout wallet for that marketplace.
3. A capability-matched execution plan, isolated production, and independent QA.
4. Explicit authorization for the first external commitment; future routine commitments only after bounded policy is configured.
5. Accepted delivery and settlement confirmation from the marketplace/payment rail.
6. Reconciliation of gross payment, platform fees, refunds, net receipt and agent ledger credit.

A listing, an escrow deposit, an invoice, a pending balance, or a local ledger record is not revenue. The engine reports revenue as zero until a separate settlement integration verifies a real payment.

## Current limits

- Taskmarket is the only source in this first slice that has an independent on-chain escrow receipt verifier.
- BasedAgents and Jobbi candidates remain review-only until their independent payment evidence and current source terms can be verified.
- The ranking is a shortlist heuristic, not a probability of winning or a profit forecast. Actual delivery costs and provider fees must be included before accepting a task.
- This is a prototype feature, not a deployed always-on service.

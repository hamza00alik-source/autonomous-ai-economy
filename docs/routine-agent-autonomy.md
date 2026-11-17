# Routine Agent Autonomy Gate

Status: local prototype component; not yet wired into the public API or production worker.

## Purpose

Give an agent permission to perform preconfigured routine commercial operations without obtaining a separate owner approval for every action. The gate is an operating-envelope check; it is not an action executor or a replacement for participant authentication, capability authorization, signed delegation, legal eligibility, platform terms or payment-provider checks.

## Initial action classes

The allowlist is intentionally narrow: demand discovery, offer drafting/publication, order acceptance, work execution/delivery, in-scope revisions and payment reconciliation. Financial transfers, custody, borrowing, leverage, permission changes and owner-grant issuance are never routine autonomous actions.

## Order exposure budget

For `accept_order`, the profile binds an agent ID, currency, per-order maximum and daily aggregate maximum. A SQLite `BEGIN IMMEDIATE` transaction reserves exposure before returning allow. An idempotency key makes retries safe and cannot be reused with changed terms. Storage errors fail closed.

This reservation is an internal exposure counter only. It does not reserve buyer funds, prove payment, authorize spending or transfer money. Production must additionally bind the decision to the authenticated participant, active capability/delegation, exact buyer agreement, verified settlement and a trusted clock.

## Current limitations

- Profiles are supplied by the caller; durable owner-signed profile provisioning is not implemented.
- Not integrated into task-offer API, marketplace publication, worker or payment adapters.
- SQLite budget reservation is single-host only.
- No real model-driven agent planner or customer channel is included.
- The module must not be described as production-ready autonomy.

## Acceptance criteria

Tests prove routine allow without per-action approval, per-order and daily exposure ceilings, idempotent retries, changed-term replay rejection, disabled-profile denial and forbidden-action rejection.


## Offer-acceptance integration

`DirectoryApplication` now accepts optional `autonomy_gate` and `autonomy_profiles` dependencies. When a provider has a configured profile, accepting a buyer-signed offer first reserves its exact quoted amount against the agent's per-order and daily exposure limits. A denied budget prevents agreement acceptance; declines are not budgeted. Providers without a configured profile retain the legacy signed-response path, so deployments must configure profiles for every autonomous provider. The profile map is currently supplied at application construction and is not yet provisioned from durable owner-signed policy records.

The API integration still records an agreement only. It does not execute the work, publish listings externally, collect buyer funds or prove settlement.

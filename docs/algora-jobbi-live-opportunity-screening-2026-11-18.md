# Algora and Jobbi live opportunity screening — 2026-11-18

## Result

The current Jobbi feed is useful for discovery but its visible agent lane is not a reliable list of easy, unclaimed tasks. The inspected candidates were stale, crowded, already delivered, or required outreach. No work was claimed or submitted.

## Candidate checks

| Listing | Advertised reward | Live source-board evidence | Decision |
|---|---:|---|---|
| lablab-ai/community-content #462 — Vectara Chat tutorial | $60 | Issue remains open, but PR #1082 was merged in September 2026; maintainers' repository guidelines prohibit AI-generated tutorial content; numerous attempts and PRs already exist | Reject: already fulfilled and AI use prohibited |
| arakoodev/EdgeChains #273 — Qdrant JS SDK | $30 | More than 40 attempts/PRs visible; multiple PRs already claim the implementation and multiple attempts show rewards | Reject: saturated, duplicate implementation risk |
| speakers-in-tech/conference-data #4, #10, #11 | $10 each | Instructions include contacting conference organizers; many attempts and PRs appeared in May and October/November 2026 | Reject: outreach required and heavily crowded |
| OpenWork Delx missions | 25,000 OPENWORK | Reward is a token with no stated USD value; payment state is only promised and payout grade D | Reject: no reliable fiat/USDC value |

## Payout eligibility note

Algora's official payment documentation lists Pakistan among supported payout countries through Stripe Connect. This is a useful possibility, not proof that a particular user account will be approved or paid. Algora still requires onboarding and valid credentials; no account was created and no payout settings were changed.

Official source: https://github.com/algora-io/algora/blob/main/priv/content/docs/payments.md

## Filter changes

The Jobbi adapter now preserves source publication/modification dates, tags, and source comment counts. Its conservative first-pass evaluator only puts a gig in the local draft queue when it has:
- positive USD/USDC reward of at least 1.00;
- platform-reported escrowed state;
- payout grade A/B;
- an open claim flag;
- known source publication date within 365 days;
- no more than 10 comments;
- no detected organizer outreach, public promotion, or core-team-only restriction.

This filter is intentionally strict. It does not follow board links, claim work, or verify a payout. Each surviving lead still requires source-board review and explicit user approval before any external commitment.

## Result

No Algora/Jobbi task currently qualifies as a low-risk first earning attempt. No account or wallet was connected. No task was claimed. Revenue remains zero.

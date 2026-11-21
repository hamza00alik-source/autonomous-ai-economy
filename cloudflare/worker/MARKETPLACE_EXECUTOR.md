# Private marketplace execution module

Cloudflare Workers module for screening marketplace task records and producing private AI drafts only.

## Safety boundary
- Does not claim tasks, submit work, publish, message, promote, spend, sign transactions, or transfer funds.
- Blocks task patterns involving deposits/stakes, wallet signing, external publishing/marketing, unsafe work, human-experience claims, and non-cash-only rewards.
- Screening is heuristic and requires hardening before broad activation.

## Files
- src/marketplace_executor.js
- migrations/0007_marketplace_execution_jobs.sql
- test/marketplace_executor.test.js

This module is not yet wired into Worker routes or cron.
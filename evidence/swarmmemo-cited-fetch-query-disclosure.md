# SwarmMemo cited-fetch query disclosure (offline reproduction)

**Status:** Reproduced against the public SwarmMemo 1.152.5 source snapshot. Not posted or claimed; no bounty acceptance or payment is implied.

## Reproduction evidence

- Upstream source commit: `2d1583945ce5ccfcc5340cd4ee2fe4011849d0b4` (the commit identifies itself as the running SwarmMemo 1.152.5 source snapshot).
- AAE GitHub Actions run: https://github.com/hamza00alik-source/autonomous-ai-economy/actions/runs/44893650864
- Both offline Go tests passed:
  - `TestAAEBountyFetchURLQuerySurvivesParsing`
  - `TestAAEBountyCitedFetchTargetExposesQuerySecret`

The tests used only the synthetic value `AAE_TEST_QUERY_SECRET_DO_NOT_USE`, a throwaway test key and an isolated local test database. They made no live fetch, no production mutation and no security probe.

## Steps and observed result

1. `parseFetchURL` accepted `https://example.test/private?token=AAE_TEST_QUERY_SECRET_DO_NOT_USE` and preserved the query string.
2. The test seeded an isolated `service_calls` row as a successful `fetch.page` result whose `final_url` contained that synthetic query token.
3. The test signed a local `service.cite` command for that call.
4. `Store.CitedCall` returned the public citation with the full query token still present in `call.target`.

The CI log printed:

```
REPRODUCED: fetch URL parser retains synthetic sensitive query value in URL: token=AAE_TEST_QUERY_SECRET_DO_NOT_USE
REPRODUCED: cited fetch target exposed synthetic query token "AAE_TEST_QUERY_SECRET_DO_NOT_USE" in public /api/calls/000000000000000000000000000000b1
```

## Source path

Pinned links:

- [fetch.go: parseFetchURL](https://github.com/Hugo0/swarmmemo/blob/2d1583945ce5ccfcc5340cd4ee2fe4011849d0b4/internal/services/fetch.go#L483-L530) accepts the query component.
- [fetch.go: readPage](https://github.com/Hugo0/swarmmemo/blob/2d1583945ce5ccfcc5340cd4ee2fe4011849d0b4/internal/services/fetch.go#L1356) stores `FinalURL: u.String()`.
- [history.go: callEntry](https://github.com/Hugo0/swarmmemo/blob/2d1583945ce5ccfcc5340cd4ee2fe4011849d0b4/internal/services/history.go#L369-L386) puts `HistoryEntry.Target` into the public history entry.
- [history.go: fetch.HistoryEntry](https://github.com/Hugo0/swarmmemo/blob/2d1583945ce5ccfcc5340cd4ee2fe4011849d0b4/internal/services/history.go#L446-L459) selects `final_url` without removing its query.
- [toolhistory.go: CitedCall](https://github.com/Hugo0/swarmmemo/blob/2d1583945ce5ccfcc5340cd4ee2fe4011849d0b4/internal/board/toolhistory.go#L230-L270) serves the cited entry publicly.
- [refused.go: fetchRefusal](https://github.com/Hugo0/swarmmemo/blob/2d1583945ce5ccfcc5340cd4ee2fe4011849d0b4/internal/services/refused.go#L10-L17) and [its URL construction](https://github.com/Hugo0/swarmmemo/blob/2d1583945ce5ccfcc5340cd4ee2fe4011849d0b4/internal/services/refused.go#L69-L86) explicitly omit query strings because they may carry tokens.

## Why it matters

An agent may fetch a signed URL or an API endpoint with an access token in its query string. If it later cites that successful fetch to prove the result, a public reader of `/api/calls/{id}` can receive the original token in `call.target`. The refused-fetch path already treats query strings as potentially sensitive, but the successful cited-fetch path does not apply the same protection.

**Suggested fix:** sanitize the target when producing a public citation (at minimum remove the query and fragment), while retaining the full target only in owner-only `service.calls` history if that is needed. Add a regression test proving that public citations never contain query values, including synthetic `token`, `api_key`, and `signature` values.

## Limits and duplicate check

A bounded public-web search for prior `service.cite` / fetch query-token disclosures found no matching report. This is not proof that no unindexed or private report exists; the requester should perform its own duplicate check.

This is a reproducible privacy-leak candidate, not evidence that any real credential was accessed or leaked. The bounty requester determines eligibility, severity and payment. No result has been submitted or claimed.

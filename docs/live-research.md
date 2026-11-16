# Public news discovery adapter

The first zero-cost live discovery adapter uses Google News' public RSS endpoint. A separate Hacker News/Algolia community-discussion adapter is also available. Both require no API key, paid plan, or third-party Python dependency.

## Run a search

```bash
economy research-news "digital products buyers demand"
economy research-news "spreadsheet templates small business" --limit 20
```

The command fetches public RSS headlines and emits candidate records containing the query, headline, publisher, article URL, publication date, and discovery timestamp.

## What this does and does not prove

- A headline is a discovery lead, not verified market evidence.
- A news article mentioning a product or trend does not prove buyers are willing to pay.
- Search results do not prove completed sales, revenue, or profitability.
- Results must be opened and checked at the original publisher; evidence must then be independently classified and entered into the existing evidence validation workflow.
- The adapter never creates `EvidenceKind.BUYER_SIGNAL` automatically and never upgrades a candidate to owner review.
- No agent automatically publishes, contacts buyers, spends, or transfers funds.

## Safety and limits

The adapter only requests HTTPS URLs on `news.google.com`, rejects redirects to other hosts, applies a 12-second timeout, limits the feed body to 1 MB, and caps each result set at 50 items. Article URLs are treated as untrusted external links and are not fetched automatically.

This is a narrow public-news discovery integration, not a general web search engine. It may miss marketplace discussions, direct buyer requests, and sales data. Google may change or limit its public RSS service. There is no guarantee of availability or completeness.

## Next integration

A separate provider interface and marketplace/source adapters can be added later. Any provider requiring credentials, paid API usage, or a metered service must remain disabled until the owner explicitly approves its cost and credentials setup.


## Manual original-source retrieval

A discovery result is only a lead. To inspect a specific original page, use the manual owner-invoked fetch command:

```bash
economy research-fetch "https://publisher.example/article" --allowed-host publisher.example
```

The exact hostname must be explicitly allowlisted by the operator. The fetcher requires HTTPS on the default port, rejects URL credentials, checks DNS answers are public IPs, rejects cross-host redirects, allows only HTML/XHTML/plain text, applies a 12-second timeout and a 1 MB response cap, and extracts a bounded text sample while excluding script/style content. It returns the fetched URL, timestamp, response metadata, SHA-256 content hash, and extracted text.

**Security and evidence boundary:** This is a defense-in-depth prototype, not a hardened browser sandbox. DNS checks cannot fully eliminate DNS-rebinding and network-layer risks in a general-purpose client. Only fetch domains you trust, preferably from a controlled environment. Retrieved text is untrusted; it may be inaccurate, manipulated, promotional, or maliciously crafted. The command does not execute page scripts, follow cross-host redirects, create evidence records, classify buyer signals, or prove a claim. Owner review and independent corroboration remain mandatory.

## Combined two-source discovery

Run both configured providers for the same search:

```bash
economy research-all "small business invoice software"
economy research-all "indie game asset packs" --limit 20
```

This calls Google News RSS and the Hacker News Search API separately, then saves both sets of candidates to the shared review queue. The command preserves provider-specific records rather than merging similar results. The two feeds are different discovery surfaces, but overlapping syndicated stories or links are possible; their co-occurrence is not independent corroboration.

## Independent community-discussion source: Hacker News

A second, separately operated discovery source is available through the public Hacker News Search API powered by Algolia. It requires no API key or paid plan.

```bash
economy research-hn "invoice workflow"
economy research-hn "small business inventory" --limit 20
```

The adapter searches public Hacker News stories, stores the HN discussion permalink, optional external article URL, author, publication timestamp, points, and comment count. It only calls HTTPS on `hn.algolia.com`, rejects cross-host redirects, applies a 12-second timeout, limits response bodies to 1 MB, and caps results at 50.

**Interpretation warning:** Hacker News is a technical-community discussion source, not a representative sample of all buyers. Points and comment counts measure platform engagement, not purchasing intent or sales. An Ask HN request or complaint is a possible qualitative problem signal only. Review the original thread, check context and date, and seek independent buyer evidence. The provider does not fetch external article URLs, create buyer-signal evidence, or verify transactions.

Google News and Hacker News are separate discovery providers, but that alone does not make two records independent evidence: the same story may be syndicated, and a discussion may link to the same article. Check the underlying source and avoid double-counting repeated material.

## Persistent local review queue

Each `research-news` search now saves leads into `./data/research.sqlite3` by default. Use `--data-dir` to choose another local data directory.

```bash
economy research-news "spreadsheet templates small business"
economy research-list
economy research-list --status unverified
economy research-review CANDIDATE_ID --note "Checked the original publisher; still need independent buyer evidence."
```

Candidate IDs are deduplicated in SQLite. Re-running a search reports how many items were newly inserted versus already present. Review status can move from `unverified` to `owner_reviewed` only through the explicit review command, which requires a non-empty note. It cannot be reset or used to manufacture buyer evidence. The original candidate payload remains unverified and `sales_verified=false`; owner review is an audit note, not proof of demand, a commercial approval, or permission to publish or spend. The local database is not encrypted or tamper-proof; keep it on a trusted device and back it up appropriately.


## Multi-query discovery

Run up to ten related searches in one command:

```bash
economy research-batch --query "small business spreadsheet template" --query "invoice template sellers" --query "inventory tracker download"
```

The coordinator deduplicates by article URL and stores the resulting leads in the same SQLite review queue. All queries still use the single Google News RSS provider. This is not multi-source corroboration: do not count multiple queries or syndicated copies as independent buyer signals.

## Evidence-readiness ranking

Start with [the example dossier](../examples/opportunities.example.json), replace every placeholder with real independently checked findings, then run:

```bash
economy rank-opportunities opportunities.json
```

Each dossier uses fields `title`, `buyer_segment`, `problem`, `proposed_solution`, `delivery_format`, `estimated_startup_cost_minor`, optional `currency`, optional `legal_risk_notes`, and an `evidence` array. Each evidence item uses `source_name`, `url`, `observed_on` (YYYY-MM-DD), `kind` (`buyer_signal`, `competitor`, `market_context`, `legal_or_policy`, or `cost`), `finding`, and optional `independent_source`.

The readiness score rewards documentation of buyer signals, competitor context, costs, legal/policy review, market context, and distinct sources. It is **not** a market-size, willingness-to-pay, sales, or profit score. The existing validator remains the stricter owner-review gate.

## Unit economics

All monetary amounts use the smallest currency unit (for USD, cents). Example:

```bash
economy unit-economics --price-minor 999 --variable-cost-minor 100 --setup-cost-minor 500 --platform-fee-bps 1000 --payment-fee-bps 300 --fixed-fee-minor 30 --units 10 --currency USD
```

Fee rates are basis points (100 bps = 1%). Include realistic platform/payment fees, taxes, refunds, chargebacks, delivery costs, and other overhead in your inputs where applicable. The result is a scenario calculation only; it does not predict sales or guarantee positive net profit.

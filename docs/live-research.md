# Public news discovery adapter

The first zero-cost live discovery adapter uses Google News' public RSS endpoint. It requires no API key, paid plan, or third-party Python dependency.

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

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


## Persistent local review queue

Each `research-news` search now saves leads into `./data/research.sqlite3` by default. Use `--data-dir` to choose another local data directory.

```bash
economy research-news "spreadsheet templates small business"
economy research-list
economy research-list --status unverified
economy research-review CANDIDATE_ID --note "Checked the original publisher; still need independent buyer evidence."
```

Candidate IDs are deduplicated in SQLite. Re-running a search reports how many items were newly inserted versus already present. Review status can move from `unverified` to `owner_reviewed` only through the explicit review command, which requires a non-empty note. It cannot be reset or used to manufacture buyer evidence. The original candidate payload remains unverified and `sales_verified=false`; owner review is an audit note, not proof of demand, a commercial approval, or permission to publish or spend. The local database is not encrypted or tamper-proof; keep it on a trusted device and back it up appropriately.

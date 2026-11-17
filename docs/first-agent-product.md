# First digital product pilot

Status: **original 3D asset source and reproducible GLB bundle implemented; engine QA, demand, listing, and sales unverified.**

## Current product candidate: MOBA Objective Props

Five original procedural low-poly fantasy props:
- Mana Crystal
- Health Vial
- Rune Altar
- Supply Chest
- Ancient Coin Stack

Each object is generated as a separate glTF 2.0 binary model (.glb). The pack also includes a combined preview scene, a Godot 4 demo scene, PBR material definitions, a README, a draft license and marketplace listing copy.

Build the ZIP:

```bash
pip install -e ".[dev,identity]"
economy-game-assets build --output dist/moba-objective-props.zip
pytest
```

The build is deterministic and includes a SHA-256 manifest. GitHub Actions also builds the ZIP and uploads it as a temporary workflow artifact. This is a downloadable prototype, not a published listing or verified commercial product.

## Market evidence and limits

The category has active marketplace listings. itch.io currently exposes hundreds of low-poly fantasy asset products, including packs priced around $2–$15; examples include character packs and modular environment/prop packs. Unity Asset Store examples include multi-hundred-object stylized fantasy environment packs priced much higher. These listings show category activity and strong competition, **not verified unit sales or demand for this specific pack**.

References:
- itch.io top-selling low-poly fantasy assets under $15: https://itch.io/game-assets/top-sellers/15-dollars-or-less/tag-fantasy/tag-low_poly
- itch.io top-selling paid low-poly fantasy assets: https://itch.io/game-assets/top-sellers/store/tag-fantasy/tag-low-poly
- Unity Asset Store stylized fantasy market pack: https://assetstore.unity.com/packages/3d/environments/fantasy/stylized-fantasy-market-low-poly-3d-art-260824

Potential differentiation to test: small, cohesive MOBA objective/consumable props delivered as individual GLB files plus a ready-to-open Godot scene. This is a hypothesis only. The current pack is deliberately modest: no rigging, animations, collision shapes, LODs, texture maps, Blender source, or Unity/Unreal-specific prefabs. It must be opened and visually inspected in Godot before any sale.

## Previous CSV tool prototype

Store Catalog Cleaner remains in the repository as a product-pipeline and packaging test. It is **not the first commercial offer**: direct competitors already sell or offer very similar CSV-cleaning utilities, including an $8.99 downloadable tool and free/paid Shopify-focused alternatives. Do not publish it as a differentiated product without substantial new capability and customer evidence.

## First payment route: crypto-first

The active payment direction is automated crypto receipt, not a bank-account-dependent payout route. The private Cloudflare Worker now has a code-only NOWPayments hosted-invoice/IPN adapter. It verifies the provider's HMAC-SHA-512 signature, matches the order and invoice, checks the USD price and full crypto amount, rejects duplicate callbacks, and marks only a fully paid `finished` event as settled. Partial or mismatched payments do not unlock delivery. The integration is not deployed and has not processed a payment. It also does not yet connect settlement to automatic file delivery.

NOWPayments states that crypto-only merchants generally do not need KYB/KYC at onboarding, but suspicious transactions can trigger checks and service may be restricted where local law requires. Its hosted payment flow uses provider infrastructure before funds reach the merchant wallet; do not describe it as non-custodial. A self-hosted BTCPay Server is the non-custodial Bitcoin/Lightning alternative, but has a server and maintenance requirement. See [crypto-first payment rail](crypto-first-payment-rail.md).

Pakistan's Virtual Assets Act, 2026 and PVARA's 2026 regulations are now in force. The Act regulates listed virtual-asset services, including custody, exchange and transfer/settlement, and contains a narrow own-account exemption in its broker-dealer schedule. That is not a blanket legal clearance for every merchant checkout. Confirm the exact activity, provider eligibility, tax and foreign-exchange treatment with qualified local counsel or PVARA before enabling crypto checkout. Do not provide exchange, custody, escrow or transfer services to third parties unless separately authorized.

## Fallback storefront: Gumroad (optional fiat route)

Gumroad currently supports local-bank payouts in Pakistan in PKR. The standard payout threshold is US$100, and bank transfers commonly take 2–7 business days after payout processing. Payoneer and Wise are not supported payout destinations; the verified Payoneer account alone does not qualify. The seller must set up a real Pakistani bank account and complete identity/address verification under their true legal details.

Commercial economics:
- Direct Gumroad sales: 10% + US$0.50 per transaction, plus card processing (currently 2.9% + US$0.30).
- Gumroad Discover marketplace sales: 30% fee, including processing.
- No monthly platform fee is listed.
- Discover is not an immediate source of first buyers: Gumroad requires payout settings, at least US$100 in genuine sales, a risk review (typically around three weeks after reaching the threshold), and at least one successful sale plus a product category before a product is eligible for Discover.

### Product creation and file upload automation

The older Gumroad Help Center API article still says product creation and content upload are unavailable. The newer official Gumroad CLI has since added both capabilities. We pinned official release `v0.20261106.1`, which supports:
- `gumroad products create --draft --file ./pack.zip` to create an unpublished product and upload the ZIP through Gumroad's multipart file flow;
- JSON output for checking the product ID and whether Gumroad reports it as published;
- separate `gumroad products publish` and `unpublish` commands.

This repository now includes two manual-only GitHub workflows:
1. **Prepare Gumroad product draft** — rebuilds the 3D pack, uses the AI copy agent, uploads the ZIP, and creates an unpublished draft at the price entered when starting the workflow.
2. **Publish Gumroad product** — requires the exact confirmation word `PUBLISH` and a product ID. It is separate from draft creation.

The draft-creation helper performs a CLI dry-run first, requests `--draft`, checks the returned `published=false` state, and stops if that state is not confirmed. If Gumroad unexpectedly reports a published product, it attempts to unpublish it and raises an error. Neither workflow has been triggered. No Gumroad account, product, token, or listing has been created by this repository work.

To use the workflows, the account owner must first deploy the private Cloudflare worker (see `docs/cloudflare-private-worker.md`), then add GitHub Actions secrets:
- `GUMROAD_ACCESS_TOKEN` — seller token with product-edit and file-upload permissions;
- `AAE_WORKER_URL` — the deployed private Cloudflare Worker origin;
- `AAE_QUEUE_TOKEN` — the same owner-only bearer secret configured in the Cloudflare Worker.

Generate the Gumroad token through the official CLI's seller OAuth login or Gumroad's application settings. Keep it in GitHub Secrets; never commit or paste it into chat. The first draft workflow does not publish. The second workflow is a separate public action requiring explicit confirmation.

Sources:
- Gumroad payout countries and thresholds: https://gumroad.com/help/article/13-getting-paid
- Gumroad Payoneer exclusion: https://gumroad.com/help/article/223-payoneer-and-gumroad
- Gumroad Discover eligibility: https://gumroad.com/help/article/79-gumroad-discover
- Official Gumroad CLI: https://github.com/antiwork/gumroad-cli
- Pinned CLI release: https://github.com/antiwork/gumroad-cli/releases/tag/v0.20261106.1
- Older Help Center API limitation notice (superseded by newer CLI capability): https://gumroad.com/help/article/76-license-keys

## Revenue monitoring

A scheduled, read-only GitHub workflow `Gumroad revenue and payout monitor` now runs daily and can also be triggered manually. It uses the official CLI to fetch aggregate sales summary and payout records, then writes a privacy-minimal report containing gross/net totals, units, refunds, and payout statuses. It deliberately excludes buyer names, emails, and individual order records. The workflow requires a Gumroad seller token with sales-view and payout-view scopes. It has not been run because no seller token is configured.

## First-sale measurement

Only count revenue after a real external buyer pays, receives the product, the payment provider confirms settlement, and net proceeds after fees/refunds are reconciled. A draft, listing, click, download, pending balance, simulated ledger entry or test order is not revenue.

Track impressions, product-page visits, conversion, refunds, support burden, platform fees, payout status and net proceeds. If no buyers arrive, change the offer based on evidence rather than multiplying unvalidated packs.

## Remaining blockers

1. Import the generated pack into Godot 4 and inspect every mesh, material, scale and demo-scene reference.
2. Verify the exact product license and marketplace AI-disclosure requirements.
3. Test the candidate with marketplace demand signals; category listings alone do not validate this product.
4. Confirm crypto-provider eligibility and the Pakistan legal/tax position before enabling the crypto checkout; keep Gumroad only as an optional fallback if its bank/KYC requirements are acceptable.
5. Connect an approved Gumroad integration with least-privilege permissions, if available, and determine how product files can be uploaded lawfully.
6. Obtain explicit publication authority before the first live listing.
7. Verify real buyer payments, refunds and cleared payouts.

The economy cannot be called always-on or revenue-generating until the production runtime, buyer channel, seller identity, payment settlement and customer support loops are live and tested.

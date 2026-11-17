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

## Candidate storefront: Gumroad

Gumroad currently lists Pakistan for local-bank payouts in PKR. The standard minimum payout is US$100; bank payout timing and verification are subject to Gumroad/Stripe review. Payoneer is not a supported Gumroad payout method, so the verified Payoneer account alone does not qualify. The account holder must complete the real local bank and identity verification.

Commercial economics:
- Direct Gumroad sales: 10% + US$0.50 per transaction, plus card processing (currently 2.9% + US$0.30).
- Gumroad Discover marketplace sales: 30% fee, including processing.
- No monthly platform fee is listed.

Critical automation limitation: Gumroad's own help centre says product creation and content upload are not currently possible through its API. This means our current agent cannot fully automate the storefront upload/publishing loop through the API. A permitted browser-based workflow may be evaluated later, but would still require a real logged-in seller account, completed identity verification, file upload and explicit publication authorization.

The repository has no Gumroad credentials, no connected seller account, and no listing. Do not store account passwords or API tokens in GitHub or chat. No product has been uploaded or published.

Sources:
- https://gumroad.com/help/article/13-getting-paid
- https://gumroad.com/help/article/66-gumroads-fees
- https://gumroad.com/help/article/76-license-keys (API product creation/content upload limitation)

## First-sale measurement

Only count revenue after a real external buyer pays, receives the product, the payment provider confirms settlement, and net proceeds after fees/refunds are reconciled. A draft, listing, click, download, pending balance, simulated ledger entry or test order is not revenue.

Track impressions, product-page visits, conversion, refunds, support burden, platform fees, payout status and net proceeds. If no buyers arrive, change the offer based on evidence rather than multiplying unvalidated packs.

## Remaining blockers

1. Import the generated pack into Godot 4 and inspect every mesh, material, scale and demo-scene reference.
2. Verify the exact product license and marketplace AI-disclosure requirements.
3. Test the candidate with marketplace demand signals; category listings alone do not validate this product.
4. Confirm Gumroad seller eligibility and local-bank payout setup for the true account holder.
5. Connect an approved Gumroad integration with least-privilege permissions, if available, and determine how product files can be uploaded lawfully.
6. Obtain explicit publication authority before the first live listing.
7. Verify real buyer payments, refunds and cleared payouts.

The economy cannot be called always-on or revenue-generating until the production runtime, buyer channel, seller identity, payment settlement and customer support loops are live and tested.

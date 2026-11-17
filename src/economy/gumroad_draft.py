"""Create an unpublished Gumroad product draft with the official Gumroad CLI.

This deliberately never publishes. The official CLI handles multipart file
uploads and returns the resulting product record. Publication is a separate
manual workflow requiring explicit owner confirmation.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import subprocess
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Callable, Mapping


def _price(value: str) -> str:
    try:
        amount = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("price must be a valid USD amount") from exc
    if not amount.is_finite() or amount <= 0 or amount > Decimal("10000"):
        raise ValueError("price must be greater than 0 and no more than 10000 USD")
    if amount.as_tuple().exponent < -2:
        raise ValueError("price may have at most two decimal places")
    return f"{amount:.2f}"


def _load_json(path: str | Path) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def _description_html(listing: dict, facts: dict) -> str:
    title = html.escape(listing["title"])
    short = html.escape(listing["short_description"])
    description = html.escape(listing["description"]).replace("\n", "<br>")
    included = "".join(f"<li>{html.escape(item)}</li>" for item in facts["included_files"])
    limits = "".join(f"<li>{html.escape(item)}</li>" for item in facts["known_limits"])
    disclosure = html.escape(listing["ai_disclosure"])
    license_summary = facts.get("license_summary")
    license_html = (
        f"<p><strong>License:</strong> {html.escape(license_summary)}</p>"
        if isinstance(license_summary, str) and license_summary.strip() else ""
    )
    return (
        f"<h2>{title}</h2><p>{short}</p><p>{description}</p>"
        f"<h3>Included</h3><ul>{included}</ul>"
        f"<h3>Technical limitations</h3><ul>{limits}</ul>"
        f"{license_html}<p><strong>AI disclosure:</strong> {disclosure}</p>"
        "<p>Review scale, materials, and engine import settings before production use.</p>"
    )


def prepare_gumroad_draft(
    *,
    bundle: str | Path,
    listing_path: str | Path,
    facts_path: str | Path,
    price_usd: str,
    output: str | Path,
    env: Mapping[str, str] | None = None,
    runner: Callable = subprocess.run,
) -> dict:
    environment = dict(os.environ if env is None else env)
    if not environment.get("GUMROAD_ACCESS_TOKEN"):
        raise RuntimeError("GUMROAD_ACCESS_TOKEN is required; store it as a secret, never in source or chat.")
    bundle_path = Path(bundle)
    if not bundle_path.is_file() or bundle_path.stat().st_size <= 0:
        raise ValueError("product bundle must exist and be non-empty")
    listing = _load_json(listing_path)
    facts = _load_json(facts_path)
    if listing.get("status") != "draft" or listing.get("published") is not False:
        raise ValueError("listing must be an unpublished AI draft")
    for key in ("title", "short_description", "description", "ai_disclosure"):
        if not isinstance(listing.get(key), str) or not listing[key].strip():
            raise ValueError(f"listing is missing {key}")
    if not isinstance(listing.get("tags"), list) or not 3 <= len(listing["tags"]) <= 10:
        raise ValueError("listing must have 3-10 tags")
    if not isinstance(facts.get("included_files"), list) or not facts["included_files"]:
        raise ValueError("product facts must list included files")
    if not isinstance(facts.get("known_limits"), list) or not facts["known_limits"]:
        raise ValueError("product facts must list technical limitations")
    price = _price(price_usd)
    cli = environment.get("GUMROAD_CLI_PATH", "gumroad")
    description = _description_html(listing, facts)
    command = [
        cli, "products", "create",
        "--name", listing["title"],
        "--price", price,
        "--currency", "usd",
        "--description", description,
        "--custom-summary", listing["short_description"],
        "--category", "3d",
        "--draft",
        "--file", str(bundle_path),
        "--file-name", bundle_path.name,
        "--file-description", "Downloadable MOBA Objective Props GLB game asset pack",
    ]
    for tag in listing["tags"]:
        if not isinstance(tag, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 _-]{1,29}", tag.strip()):
            raise ValueError("listing contains an invalid tag")
        command.extend(["--tag", tag.strip()])
    base_flags = ["--json", "--no-input", "--quiet"]
    dry = runner(command + ["--dry-run"] + base_flags, capture_output=True, text=True, env=environment, check=False)
    if dry.returncode != 0:
        raise RuntimeError("Gumroad draft dry-run failed: " + (dry.stderr or dry.stdout or "unknown error")[:1000])
    try:
        dry_result = json.loads(dry.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Gumroad CLI did not return valid dry-run JSON") from exc
    if dry_result.get("dry_run") is not True:
        raise RuntimeError("Gumroad CLI dry-run did not confirm dry_run=true")

    result = runner(command + base_flags, capture_output=True, text=True, env=environment, check=False)
    if result.returncode != 0:
        raise RuntimeError("Gumroad draft creation failed; inspect CLI recovery guidance: " + (result.stderr or result.stdout or "unknown error")[:1500])
    try:
        payload = json.loads(result.stdout)
        if payload.get("success") is not True:
            raise RuntimeError("Gumroad CLI did not confirm success=true")
        product = payload["product"]
        product_id = product["id"]
        published = product["published"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise RuntimeError("Gumroad CLI response did not confirm the created product state") from exc
    if not isinstance(product_id, str) or not product_id:
        raise RuntimeError("Gumroad CLI returned an invalid product ID")
    if published is not False:
        rollback = runner(
            [cli, "products", "unpublish", product_id, "--yes"] + base_flags,
            capture_output=True, text=True, env=environment, check=False,
        )
        raise RuntimeError(
            "Safety stop: Gumroad reported the product as published; "
            f"automatic unpublish exit code={rollback.returncode}. Check the seller dashboard immediately."
        )
    summary = {
        "product_id": product_id,
        "name": product.get("name", listing["title"]),
        "formatted_price": product.get("formatted_price"),
        "short_url": product.get("short_url"),
        "published": False,
        "draft_created": True,
        "file_uploaded": True,
        "publication_authorized": False,
    }
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd = os.open(output_path, flags, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2)
        handle.write("\n")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a draft-only Gumroad product and upload its ZIP")
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--listing", type=Path, required=True)
    parser.add_argument("--facts", type=Path, required=True)
    parser.add_argument("--price-usd", required=True)
    parser.add_argument("--output", type=Path, default=Path("dist/gumroad-draft-result.json"))
    args = parser.parse_args()
    result = prepare_gumroad_draft(
        bundle=args.bundle, listing_path=args.listing, facts_path=args.facts,
        price_usd=args.price_usd, output=args.output,
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

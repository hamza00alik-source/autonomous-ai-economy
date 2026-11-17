"""Sanitize Gumroad aggregate sales/payout data into a privacy-minimal report."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


def build_report(sales_path: str | Path, payouts_path: str | Path) -> dict:
    sales = json.loads(Path(sales_path).read_text(encoding="utf-8"))
    payouts = json.loads(Path(payouts_path).read_text(encoding="utf-8"))
    if sales.get("success") is not True or payouts.get("success") is not True:
        raise ValueError("Gumroad did not confirm successful sales and payout responses")
    sales_fields = (
        "gross_cents", "net_cents", "units", "refunded_cents",
        "refunded_units", "currency", "from", "to",
    )
    summary = {key: sales.get(key) for key in sales_fields}
    breakdown_fields = ("key", "label", "gross_cents", "net_cents", "units", "refunded_cents", "refunded_units")
    breakdown = [
        {key: item.get(key) for key in breakdown_fields}
        for item in sales.get("breakdown", [])
        if isinstance(item, dict)
    ]
    payout_fields = (
        "id", "payout_period", "amount_cents", "formatted_amount",
        "is_upcoming", "display_payout_period",
    )
    payout_rows = []
    for row in payouts.get("payouts", []):
        if not isinstance(row, dict):
            raise ValueError("invalid payout row")
        payout_rows.append({key: row.get(key) for key in payout_fields})
    return {
        "schema": "aae.gumroad-revenue-report/v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sales_summary": summary,
        "product_breakdown": breakdown,
        "payouts": payout_rows,
        "privacy": {
            "buyer_emails_included": False,
            "buyer_names_included": False,
            "individual_sales_included": False,
        },
        "revenue_definition": "Gumroad net sales summary is platform-reported net sales, not proof that a bank payout has cleared.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build privacy-minimal Gumroad sales and payout report")
    parser.add_argument("--sales", type=Path, required=True)
    parser.add_argument("--payouts", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = build_report(args.sales, args.payouts)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)
        handle.write("\n")
    print(json.dumps({
        "report": str(args.output),
        "units": report["sales_summary"]["units"],
        "net_cents": report["sales_summary"]["net_cents"],
        "payout_count": len(report["payouts"]),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

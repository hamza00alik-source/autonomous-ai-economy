from __future__ import annotations

import json

import pytest

from tools.build_gumroad_revenue_report import build_report


def test_revenue_report_contains_aggregates_but_no_buyer_data(tmp_path):
    sales = tmp_path / "sales.json"
    payouts = tmp_path / "payouts.json"
    sales.write_text(json.dumps({
        "success": True, "gross_cents": 5000, "net_cents": 3555,
        "units": 1, "refunded_cents": 0, "refunded_units": 0,
        "currency": "USD", "from": "2026-01-01", "to": "2026-11-17",\n        "breakdown": [{"key": "prod-1", "label": "MOBA Objective Props", "gross_cents": 5000, "net_cents": 3555, "units": 1, "refunded_cents": 0, "refunded_units": 0, "buyer_email": "private@example.com"}],
        "buyers": [{"email": "private@example.com"}],
    }))
    payouts.write_text(json.dumps({
        "success": True,
        "payouts": [{
            "id": "pay-1", "payout_period": "2026-11-01",
            "amount_cents": 3555, "formatted_amount": "$35.55",
            "is_upcoming": False, "display_payout_period": "Nov 1-7",
            "email": "private@example.com",
        }],
    }))
    report = build_report(sales, payouts)
    assert report["sales_summary"]["net_cents"] == 3555\n    assert report["product_breakdown"][0]["key"] == "prod-1"\n    assert "buyer_email" not in report["product_breakdown"][0]
    assert report["payouts"][0]["id"] == "pay-1"
    assert "email" not in report["payouts"][0]
    assert report["privacy"]["buyer_emails_included"] is False


def test_revenue_report_requires_successful_platform_responses(tmp_path):
    sales = tmp_path / "sales.json"
    payouts = tmp_path / "payouts.json"
    sales.write_text(json.dumps({"success": False}))
    payouts.write_text(json.dumps({"success": True, "payouts": []}))
    with pytest.raises(ValueError, match="did not confirm"):
        build_report(sales, payouts)

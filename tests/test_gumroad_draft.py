from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

from economy.gumroad_draft import prepare_gumroad_draft, _price


def _inputs(tmp_path):
    bundle = tmp_path / "asset-pack.zip"
    bundle.write_bytes(b"zip-bytes")
    listing = tmp_path / "listing.json"
    listing.write_text(json.dumps({
        "title": "MOBA Objective Props - Five Low-Poly GLB Models",
        "short_description": "Five low-poly fantasy props in GLB format for Godot 4 prototypes.",
        "description": "Five original low-poly fantasy props. Includes five GLB models and a Godot 4 demo scene.",
        "tags": ["low-poly", "GLB models", "Godot assets"],
        "ai_disclosure": "AI-assisted procedural mesh generation.",
        "status": "draft",
        "published": False,
    }))
    facts = tmp_path / "facts.json"
    facts.write_text(json.dumps({
        "included_files": ["five GLB models", "Godot 4 demo scene"],
        "known_limits": ["static props only", "no animation"],
    }))
    return bundle, listing, facts


def test_price_is_validated_and_normalized():
    assert _price("5") == "5.00"
    assert _price("5.5") == "5.50"
    for value in ("0", "-1", "10001", "1.001", "NaN", "bad"):
        with pytest.raises(ValueError):
            _price(value)


def test_draft_creation_dry_runs_then_creates_unpublished_product(tmp_path):
    bundle, listing, facts = _inputs(tmp_path)
    calls = []

    def runner(command, **kwargs):
        calls.append(command)
        if "--dry-run" in command:
            return SimpleNamespace(returncode=0, stdout='{"dry_run":true}', stderr="")
        return SimpleNamespace(returncode=0, stdout=json.dumps({
            "success": True,
            "product": {
                "id": "prod-123",
                "name": "MOBA Objective Props",
                "formatted_price": "$5.00",
                "short_url": "https://example.gumroad.com/l/props",
                "published": False,
            },
        }), stderr="")

    output = tmp_path / "out" / "result.json"
    result = prepare_gumroad_draft(
        bundle=bundle, listing_path=listing, facts_path=facts, price_usd="5",
        output=output, env={"GUMROAD_ACCESS_TOKEN": "secret"}, runner=runner,
    )
    assert len(calls) == 2
    assert "--dry-run" in calls[0]
    assert "--draft" in calls[0]
    assert "--draft" in calls[1]
    assert "--file" in calls[1]
    assert result["published"] is False
    assert result["product_id"] == "prod-123"
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert json.loads(output.read_text())["publication_authorized"] is False
    assert "secret" not in output.read_text()


def test_draft_creation_refuses_missing_token_and_never_calls_cli(tmp_path):
    bundle, listing, facts = _inputs(tmp_path)
    calls = []
    with pytest.raises(RuntimeError, match="GUMROAD_ACCESS_TOKEN"):
        prepare_gumroad_draft(
            bundle=bundle, listing_path=listing, facts_path=facts, price_usd="5",
            output=tmp_path / "result.json", env={}, runner=lambda *a, **k: calls.append(a),
        )
    assert calls == []


def test_draft_creation_refuses_published_response_and_rolls_back(tmp_path):
    bundle, listing, facts = _inputs(tmp_path)
    calls = []

    def runner(command, **kwargs):
        calls.append(command)
        if "--dry-run" in command:
            return SimpleNamespace(returncode=0, stdout='{"dry_run":true}', stderr="")
        if "unpublish" in command:
            return SimpleNamespace(returncode=0, stdout='{"success":true}', stderr="")
        return SimpleNamespace(returncode=0, stdout=json.dumps({
            "success": True,
            "product": {"id": "prod-live", "published": True}
        }), stderr="")

    with pytest.raises(RuntimeError, match="Safety stop"):
        prepare_gumroad_draft(
            bundle=bundle, listing_path=listing, facts_path=facts, price_usd="5",
            output=tmp_path / "result.json", env={"GUMROAD_ACCESS_TOKEN": "secret"}, runner=runner,
        )
    assert any("unpublish" in call for call in calls)
    assert not (tmp_path / "result.json").exists()


def test_draft_creation_rejects_non_draft_copy_before_api_call(tmp_path):
    bundle, listing, facts = _inputs(tmp_path)
    data = json.loads(listing.read_text())
    data["published"] = True
    listing.write_text(json.dumps(data))
    calls = []
    with pytest.raises(ValueError, match="unpublished"):
        prepare_gumroad_draft(
            bundle=bundle, listing_path=listing, facts_path=facts, price_usd="5",
            output=tmp_path / "result.json", env={"GUMROAD_ACCESS_TOKEN": "secret"},
            runner=lambda *a, **k: calls.append(a),
        )
    assert calls == []

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from economy.ai_product_agent import (
    AIProductCopyAgent, ProductCopyValidationError,
)


class FakeModel:
    def __init__(self, text):
        self.text = text
        self.calls = []

    def generate(self, prompt, *, system, max_tokens=512):
        self.calls.append({"prompt": prompt, "system": system, "max_tokens": max_tokens})
        return SimpleNamespace(text=self.text)


@pytest.fixture
def facts():
    return {
        "product_name": "MOBA Objective Props",
        "buyer_segment": "Indie game developers and hobbyists",
        "product_summary": "Five original low-poly fantasy props for game prototypes.",
        "included_files": ["five individual GLB models", "combined preview GLB", "Godot 4 demo scene"],
        "formats": ["GLB", "Godot 4"],
        "known_limits": ["static props only", "no rigging", "no animation", "no collision shapes"],
        "ai_disclosure": "AI-assisted procedural mesh generation.",
    }


def valid_copy():
    return {
        "title": "MOBA Objective Props - Five Low-Poly GLB Models",
        "short_description": "Five low-poly fantasy props in GLB format for Godot 4 prototypes.",
        "description": (
            "MOBA Objective Props is a small collection of five original low-poly fantasy props. "
            "The download includes individual GLB models, a combined preview GLB, and a Godot 4 demo scene. "
            "These are static props only, with no rigging, animation, or collision shapes. "
            "AI-assisted procedural mesh generation."
        ),
        "tags": ["low-poly", "GLB models", "Godot assets"],
        "ai_disclosure": "AI-assisted procedural mesh generation.",
        "claims_to_verify": ["Inspect import scale and materials in the target Godot version."],
    }


def test_agent_returns_only_validated_draft_and_uses_supplied_facts(facts):
    model = FakeModel(json.dumps(valid_copy()))
    result = AIProductCopyAgent(model).draft(facts)
    assert result.status == "draft"
    assert result.published is False
    assert "GLB" in result.description
    assert model.calls[0]["max_tokens"] == 512
    assert "Do not invent features" in model.calls[0]["prompt"]


def test_agent_rejects_unsupported_claims(facts):
    data = valid_copy()
    data["description"] += " Best-selling asset pack with guaranteed results."
    with pytest.raises(ProductCopyValidationError, match="unsupported"):
        AIProductCopyAgent(FakeModel(json.dumps(data))).draft(facts)


def test_agent_rejects_missing_ai_disclosure(facts):
    data = valid_copy()
    data["ai_disclosure"] = "Created by a human studio."
    with pytest.raises(ProductCopyValidationError, match="omitted"):
        AIProductCopyAgent(FakeModel(json.dumps(data))).draft(facts)


def test_agent_rejects_invalid_or_extra_json_fields(facts):
    with pytest.raises(ProductCopyValidationError, match="valid JSON"):
        AIProductCopyAgent(FakeModel("not json")).draft(facts)
    data = valid_copy()
    data["publish_now"] = True
    with pytest.raises(ProductCopyValidationError, match="unexpected"):
        AIProductCopyAgent(FakeModel(json.dumps(data))).draft(facts)


def test_agent_rejects_incomplete_product_facts(facts):
    del facts["known_limits"]
    with pytest.raises(ProductCopyValidationError, match="missing product facts"):
        AIProductCopyAgent(FakeModel("{}")).draft(facts)

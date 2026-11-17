import test from "node:test";
import assert from "node:assert/strict";
import { validFacts, validateDraft, estimateNeurons, constantTimeEqual, DAILY_NEURON_BUDGET } from "../src/index.js";

const facts = {
  product_name: "MOBA Objective Props",
  buyer_segment: "Indie game developers and hobbyists",
  product_summary: "Five original low-poly fantasy props for game prototypes.",
  included_files: ["five individual GLB models", "combined preview GLB", "Godot 4 demo scene"],
  formats: ["GLB", "Godot 4"],
  known_limits: ["static props only", "no rigging", "no animation", "no collision shapes"],
  ai_disclosure: "AI-assisted procedural mesh generation."
};

const draft = {
  title: "MOBA Objective Props - Five Low-Poly GLB Models",
  short_description: "Five low-poly fantasy props in GLB format for Godot 4 prototypes.",
  description: "MOBA Objective Props is a small collection of five original low-poly fantasy props. Includes GLB models and a Godot 4 demo scene. Static props only, with no rigging or animation. AI-assisted procedural mesh generation.",
  tags: ["low-poly", "GLB models", "Godot assets"],
  ai_disclosure: "AI-assisted procedural mesh generation.",
  claims_to_verify: ["Inspect import scale and materials in Godot."]
};

test("facts validator accepts the real product fact sheet", () => {
  assert.equal(validFacts(facts), null);
});

test("facts validator rejects prompt injection fields and missing limitations", () => {
  assert.match(validFacts({ ...facts, publish_now: true }), /unexpected/);
  const broken = { ...facts };
  delete broken.known_limits;
  assert.match(validFacts(broken), /missing/);
});

test("draft validator accepts bounded unpublished copy", () => {
  const result = validateDraft(draft, facts);
  assert.equal(result.status, "draft");
  assert.equal(result.published, false);
  assert.equal(result.tags.length, 3);
});

test("draft validator rejects unsupported performance claims and omitted disclosure", () => {
  assert.throws(() => validateDraft({ ...draft, description: draft.description + " Best-selling and guaranteed." }, facts), /unsupported/);
  assert.throws(() => validateDraft({ ...draft, ai_disclosure: "Human-created only." }, facts), /disclosure/);
});

test("budget estimator remains bounded and uses a safety margin", () => {
  const estimate = estimateNeurons(facts);
  assert.ok(estimate > 0 && estimate < DAILY_NEURON_BUDGET);
});

test("constant time comparison handles equal and unequal secrets", () => {
  assert.equal(constantTimeEqual("secret", "secret"), true);
  assert.equal(constantTimeEqual("secret", "secreu"), false);
});

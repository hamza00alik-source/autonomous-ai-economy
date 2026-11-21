import test from "node:test";
import assert from "node:assert/strict";
import { qualityCheckDraft } from "../src/marketplace_quality.js";

test("draft with content, self-review, and evidence URLs passes candidate screening", () => {
  const task = { title: "Write a concise product comparison" };
  const draft = "Comparison summary with useful details. Self-check: assumptions noted. Source: https://example.com/reference";
  const result = qualityCheckDraft(task, draft);
  assert.equal(result.status, "submission_candidate");
  assert.deepEqual(result.blockers, []);
  assert.equal(result.sourceUrls.length, 1);
});

test("unfinished draft is blocked", () => {
  const result = qualityCheckDraft({ title: "Task" }, "TODO: finish this later. Self-check pending.");
  assert.equal(result.status, "needs_revision");
  assert.ok(result.blockers.includes("draft_too_short"));
  assert.ok(result.blockers.includes("unfinished_markers_found"));
});

test("missing self-review is flagged", () => {
  const result = qualityCheckDraft({ title: "Task" }, "This is a long enough draft to be reviewed but it contains no self review section and no evidence link.");
  assert.ok(result.blockers.includes("missing_self_review"));
});

test("claims of live verification require evidence review", () => {
  const result = qualityCheckDraft({ title: "Task" }, "This draft is long enough for the automated checker to inspect. Self-check: I verified this claim. Source: https://example.com");
  assert.ok(result.blockers.includes("verification_claims_require_evidence"));
});

import test from "node:test";
import assert from "node:assert/strict";
import { qualityCheckDraft } from "../src/marketplace_quality.js";

const passingReview = {
  pass: true, issues: [], failedCriteria: [],
  criteria: [{ criterion: "Include limitations", passed: true, evidence: "A limitations section is present." }],
};

test("draft passes only with independent review and evidence for each acceptance criterion", () => {
  const task = { title: "Write a concise product comparison", acceptanceCriteria: ["Include limitations"] };
  const draft = "Comparison summary with useful details. Limitations are explained. Self-check: assumptions noted. Source: https://example.com/reference";
  const result = qualityCheckDraft(task, draft, passingReview);
  assert.equal(result.status, "submission_candidate");
  assert.deepEqual(result.blockers, []);
  assert.equal(result.sourceUrls.length, 1);
  assert.equal(result.independentlyReviewed, true);
});

test("unfinished draft is blocked", () => {
  const result = qualityCheckDraft({ title: "Task" }, "TODO: finish this later. Self-check pending.", {pass:true,issues:[],failedCriteria:[],criteria:[]});
  assert.equal(result.status, "needs_revision");
  assert.ok(result.blockers.includes("draft_too_short"));
  assert.ok(result.blockers.includes("unfinished_markers_found"));
});

test("missing self-review is flagged", () => {
  const result = qualityCheckDraft({ title: "Task" }, "This is a long enough draft to be reviewed but it contains no self review section and no evidence link.", {pass:true,issues:[],failedCriteria:[],criteria:[]});
  assert.ok(result.blockers.includes("missing_self_review"));
});

test("claims of live verification require evidence review", () => {
  const result = qualityCheckDraft({ title: "Task" }, "This draft is long enough for the automated checker to inspect. Self-check: I verified this claim. Source: https://example.com", {pass:true,issues:[],failedCriteria:[],criteria:[]});
  assert.ok(result.blockers.includes("verification_claims_require_evidence"));
});

test("a missing or failed independent review blocks submission readiness", () => {
  const draft = "A sufficiently detailed draft. Self-check: limitations and assumptions are stated. Source: https://example.com";
  const missing = qualityCheckDraft({title:"Task"}, draft);
  const failed = qualityCheckDraft({title:"Task"}, draft, {pass:false,issues:["Unsupported claim"],failedCriteria:[],criteria:[]});
  assert.ok(missing.blockers.includes("independent_review_not_passed"));
  assert.ok(failed.blockers.includes("independent_review_not_passed"));
});

test("missing criterion evidence blocks submission readiness", () => {
  const task = {title:"Task",acceptanceCriteria:["Include limitations"]};
  const review = {pass:true,issues:[],failedCriteria:[],criteria:[]};
  const result = qualityCheckDraft(task, "A sufficiently detailed draft. Self-check: limitations and assumptions are stated. Source: https://example.com", review);
  assert.ok(result.blockers.includes("acceptance_criteria_not_verified"));
});

test("source URL extraction is repeatable across calls", () => {
  const draft = "Self-check: all assumptions are stated. See https://example.com/a and https://example.org/b for sources.";
  const review = {pass:true,issues:[],failedCriteria:[],criteria:[]};
  const first = qualityCheckDraft({title:"Task"}, draft, review);
  const second = qualityCheckDraft({title:"Task"}, draft, review);
  assert.deepEqual(first.sourceUrls, second.sourceUrls);
  assert.equal(first.sourceUrls.length, 2);
});

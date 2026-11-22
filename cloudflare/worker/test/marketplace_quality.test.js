import test from "node:test";
import assert from "node:assert/strict";
import { qualityCheckDraft } from "../src/marketplace_quality.js";

const passingReview = {pass:true,issues:[],failedCriteria:[],provider:"google",independent:true,sameProvider:false,criteria:[{criterion:"Include limitations",passed:true,evidence:"Limitations are explained."}]};

test("draft passes only with review and exact evidence for each acceptance criterion",()=>{
  const task={title:"Write a concise product summary",acceptanceCriteria:["Include limitations"]};
  const draft="Comparison summary with useful details. Limitations are explained. Self-check: assumptions noted. Source: https://example.com/reference";
  const result=qualityCheckDraft(task,draft,passingReview);
  assert.equal(result.status,"submission_candidate");
  assert.deepEqual(result.blockers,[]);
  assert.equal(result.sourceUrls.length,1);
  assert.equal(result.independentlyReviewed,true);
  assert.equal(result.reviewMode,"google_independent_provider");
  assert.equal(result.reviewerCallPassed,true);
});

test("unfinished draft is blocked",()=>{
  const result=qualityCheckDraft({title:"Task"},"TODO: finish this later. Self-check pending.",{pass:true,issues:[],failedCriteria:[],criteria:[]});
  assert.equal(result.status,"needs_revision");
  assert.ok(result.blockers.includes("draft_too_short"));
  assert.ok(result.blockers.includes("unfinished_markers_found"));
});

test("missing self-review is flagged",()=>{
  const result=qualityCheckDraft({title:"Task"},"This is a long enough draft to be reviewed but it contains no self review section and no evidence link.",{pass:true,issues:[],failedCriteria:[],criteria:[]});
  assert.ok(result.blockers.includes("missing_self_review"));
});

test("claims of live verification require evidence review",()=>{
  const result=qualityCheckDraft({title:"Task"},"This draft is long enough for the automated checker to inspect. Self-check: I verified this claim. Source: https://example.com",{pass:true,issues:[],failedCriteria:[],criteria:[]});
  assert.ok(result.blockers.includes("verification_claims_require_evidence"));
});

test("missing or failed same-model review blocks readiness",()=>{
  const draft="A sufficiently detailed draft. Self-check: limitations and assumptions are stated. Source: https://example.com";
  assert.ok(qualityCheckDraft({title:"Task"},draft).blockers.includes("independent_provider_review_not_passed"));
  assert.ok(qualityCheckDraft({title:"Task"},draft,{pass:false,issues:["Unsupported claim"],failedCriteria:[],criteria:[]}).blockers.includes("independent_provider_review_not_passed"));
});

test("missing criterion evidence blocks readiness",()=>{
  const result=qualityCheckDraft({title:"Task",acceptanceCriteria:["Include limitations"]},"A sufficiently detailed draft. Self-check: limitations and assumptions are stated. Source: https://example.com",{pass:true,issues:[],failedCriteria:[],criteria:[]});
  assert.ok(result.blockers.includes("acceptance_criteria_not_verified"));
});

test("source URL extraction is stable",()=>{
  const draft="Self-check: all assumptions are stated. See https://example.com/a and https://example.org/b for sources.";
  const first=qualityCheckDraft({title:"Task"},draft,passingReview);
  const second=qualityCheckDraft({title:"Task"},draft,passingReview);
  assert.deepEqual(first.sourceUrls,second.sourceUrls);
  assert.equal(first.sourceUrls.length,2);
});

test("research requires fetched, relevant source evidence and exact draft excerpt",()=>{
  const task={title:"Research a software market",description:"Investigate the market and compare current offerings"};
  const draft="A substantive research draft with analysis and limitations. Self-check: assumptions are stated. Evidence: exact supporting passage from the cited page.";
  const review={pass:true,issues:[],failedCriteria:[],criteria:[]};
  const absent=qualityCheckDraft(task,draft+" Source: https://example.com/report",review);
  assert.ok(absent.blockers.includes("source_retrieval_not_verified"));
  const verified={status:"retrieved_unverified",verified:false,retrievalVerified:true,blockers:[],results:[{
    requestedUrl:"https://example.com/report",httpStatus:200,supportsClaims:false,excerptMatched:true,verificationStatus:"retrieved_unverified",
    sourceExcerpt:"exact supporting passage from the cited page.",
    draftExcerpt:"exact supporting passage from the cited page.",
  }]};
  const passed=qualityCheckDraft(task,draft+" Source: https://example.com/report",review,verified);
  assert.equal(passed.sourceRetrievalVerified,true);
  assert.equal(passed.sourceContentVerified,false);
  assert.ok(!passed.blockers.includes("source_retrieval_not_verified"));
});

test("verifier error remains a blocker",()=>{
  const task={title:"Research current market",description:"Compare current products"};
  const result=qualityCheckDraft(task,"A substantive report with limitations. Self-check: assumptions stated. Source: https://example.com",passingReview,{status:"unavailable",verified:false,blockers:["source_verifier_unavailable"]});
  assert.ok(result.blockers.includes("source_verifier_unavailable"));
  assert.equal(result.status,"needs_revision");
});

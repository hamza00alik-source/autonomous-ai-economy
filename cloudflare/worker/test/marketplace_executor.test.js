import test from "node:test";
import assert from "node:assert/strict";
import { assessTask, executePrivateDraft } from "../src/marketplace_executor.js";

const goodDraft = "Documentation draft: This guide explains the supplied software feature, its setup steps, expected behavior, and practical limitations. Source: https://example.com/docs. Self-check: verify every step against the current official documentation before use.";
const reviewerPass = JSON.stringify({ pass: true, issues: [], reason: "The deliverable directly addresses the task and avoids unsupported claims.", criteria: [] });

test("screens eligible tasks into private draft lane", () => {
  const result = assessTask({id:"t1",title:"Review open source docs",description:"Review docs and suggest improvements",eligible:true,reward_usdc:"1.00"});
  assert.equal(result.eligible,true);
});
test("preserves buyer acceptance criteria and delivery constraints", () => {
  const result = assessTask({
    title:"Review docs", description:"Produce a review", reward_usdc:"1.00",
    acceptance_criteria:["Link every factual claim"], required_deliverables:["Markdown report"],
    constraints:["No paid APIs"], output_format:"Markdown",
  });
  assert.deepEqual(result.acceptanceCriteria, ["Link every factual claim"]);
  assert.deepEqual(result.requiredDeliverables, ["Markdown report"]);
  assert.deepEqual(result.constraints, ["No paid APIs"]);
  assert.equal(result.outputFormat, "Markdown");
});
test("blocks stake and external publishing risks", () => {
  for (const task of [
    {title:"Deposit required",description:"Stake to enter"},
    {title:"Post social content",description:"Publish a marketing post"},
    {title:"Connect wallet",description:"Sign transaction"},
  ]) assert.equal(assessTask(task).eligible,false);
});
test("blocks placeholder titles and unsupported media production", () => {
  for (const task of [
    {title:"## Title",description:"Create a useful deliverable"},
    {title:"Untitled",description:"Write a short note"},
    {title:"Create a story",description:"Produce the final video with recorded voiceover"},
  ]) assert.equal(assessTask(task).eligible,false);
  assert.ok(assessTask({title:"## Title",description:"Create a useful deliverable"}).reasons.includes("malformed_task_title"));
  assert.ok(assessTask({title:"Create a story",description:"Produce the final video with recorded voiceover"}).reasons.includes("unsupported_deliverable"));
});
test("allows a well-formed text task", () => {
  const result=assessTask({title:"Review open source documentation",description:"Write a concise documentation review and list actionable improvements.",eligible:true,reward_usdc:"1.00"});
  assert.equal(result.eligible,true);
});
test("blocks credits-only task", () => {
  assert.ok(assessTask({title:"task",description:"work",reward_credits:20,credits_only:true}).reasons.includes("non_cash_reward"));
});
test("requires a positive USDC reward", () => {
  for (const reward of [null, undefined, 0, "0", "-1", "pending", "1 ETH"]) {
    const result = assessTask({title:"Review documentation",description:"Write a useful documentation review.",reward});
    assert.equal(result.eligible,false);
    assert.ok(result.reasons.includes("reward_not_positive_verified_usdc"));
  }
  assert.equal(assessTask({title:"Review documentation",description:"Write a useful documentation review.",reward:"1.000000"}).eligible,true);
});
test("private execution requires independent review and takes no external action", async () => {
  const outputs = [goodDraft, reviewerPass];
  const env={AI:{run:async()=>({response:outputs.shift()})}};
  const result=await executePrivateDraft(env,{id:"t",title:"Research docs",description:"Summarize provided documentation",eligible:true,reward_usdc:"0.1"});
  assert.equal(result.status,"draft_ready");
  assert.equal(result.externalActionsTaken,false);
  assert.equal(result.agentTeam.length,2);
  assert.equal(result.submissionReady,true);
  assert.match(result.deliverableSha256, /^[a-f0-9]{64}$/);
  assert.ok(result.qa.checks.some(check=>check.id==="independent_review" && check.passed));
});
test("criterion failure blocks submission readiness even after one revision", async () => {
  const criterion = "Include limitations";
  const outputs = [
    goodDraft,
    JSON.stringify({pass:false,issues:["Add limitations"],reason:"Missing section",criteria:[{criterion,passed:false,evidence:"No limitations section."}]}),
    goodDraft,
    JSON.stringify({pass:false,issues:["Still missing limitations"],reason:"Revision did not fix the gap",criteria:[{criterion,passed:false,evidence:"Still absent."}]}),
  ];
  const result=await executePrivateDraft({AI:{run:async()=>({response:outputs.shift()})}},{
    id:"t",title:"Research docs",description:"Summarize provided documentation",
    eligible:true,reward_usdc:"0.1",acceptance_criteria:[criterion],
  });
  assert.equal(result.submissionReady,false);
  assert.ok(result.qa.blockers.includes("independent_review_not_passed"));
  assert.ok(result.qa.blockers.includes("acceptance_criteria_not_verified"));
});
test("rejects empty specialist output", async () => {
  await assert.rejects(()=>executePrivateDraft({AI:{run:async()=>({})}},{title:"Research",description:"Draft a research note",eligible:true,reward_usdc:"1.00"}),/specialist agent returned no usable output/);
});

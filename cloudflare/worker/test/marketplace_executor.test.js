import test from "node:test";
import assert from "node:assert/strict";
import { assessTask, executePrivateDraft, scoreTask } from "../src/marketplace_executor.js";

const goodDraft = "Documentation draft: This guide explains the supplied software feature, its setup steps, expected behavior, and practical limitations. Source: https://example.com/docs. Self-check: verify every step against the current official documentation before use.";
const reviewerPass = '{"pass":true,"issues":[],"reason":"The deliverable directly addresses the task and avoids unsupported claims."}';

test("screens eligible tasks into private draft lane", () => {
  const result = assessTask({id:"t1",title:"Review open source docs",description:"Review docs and suggest improvements",eligible:true,reward_usdc:"1.00"});
  assert.equal(result.eligible,true);
});
test("blocks stake and external publishing risks", () => {
  for (const task of [
    {title:"Deposit required",description:"Stake to enter"},
    {title:"Post social content",description:"Publish a post on a social platform"},
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
test("aggregator source-policy verification is a separate hard gate", () => {
  const result = assessTask({
    title: "Write a documented technical guide",
    description: "Create a clear guide with acceptance criteria and source links.",
    eligible: false, source_policy_verified: false, reward: "5.00",
  });
  assert.equal(result.eligible, false);
  assert.ok(result.reasons.includes("source_policy_unverified"));
});

test("blocks credits-only task", () => {
  assert.ok(assessTask({title:"task",description:"work",reward_credits:20,credits_only:true}).reasons.includes("non_cash_reward"));
});
test("requires a positive USDC reward", () => {
  for (const reward of [null, undefined, 0, "0", "-1", "pending", "1 ETH"]) {
    const result = assessTask({title:"Review documentation",description:"Write a useful documentation review.",reward});
    assert.equal(result.eligible,false);
    assert.ok(result.reasons.includes("reward_not_positive_verified_amount"));
  }
  assert.equal(assessTask({title:"Review documentation",description:"Write a useful documentation review.",reward:"1.000000"}).eligible,true);
});
test("private execution runs specialist and independent reviewer but takes no external action", async () => {
  const outputs = [goodDraft, reviewerPass];
  const env={AI:{run:async()=>({response:outputs.shift()})}};
  const result=await executePrivateDraft(env,{id:"t",title:"Research docs",description:"Summarize provided documentation",eligible:true,reward_usdc:"0.1"});
  assert.equal(result.status,"draft_ready");
  assert.equal(result.externalActionsTaken,false);
  assert.equal(result.agentTeam.length,2);
  assert.equal(result.submissionReady,true);
});
test("rejects empty specialist output", async () => {
  await assert.rejects(()=>executePrivateDraft({AI:{run:async()=>({})}},{title:"Research",description:"Draft a research note",eligible:true,reward_usdc:"1.00"}),/specialist agent returned no usable output/);
});

test("allows marketing-copy drafts but blocks external social publishing", () => {
  const draft = assessTask({title:"Write social media marketing copy",description:"Draft three promotional captions for a product.",eligible:true,reward_usdc:"1.00"});
  assert.equal(draft.eligible,true);
  const publish = assessTask({title:"Publish product announcement",description:"Post the announcement on our public social account.",eligible:true,reward_usdc:"1.00"});
  assert.equal(publish.eligible,false);
});


test("blocks Chinese video-production tasks from the text-only execution lane", () => {
  const task = assessTask({title:"制作一个约20分钟的视频",description:"制作完整视频成片并完成配音、字幕和剪辑。",eligible:true,reward_usdc:"1.00"});
  assert.equal(task.eligible,false);
  assert.ok(task.reasons.includes("unsupported_deliverable"));
});


test("blocks all excluded task requirements before execution", () => {
  const blockedTasks = [
    { title: "Create an account", description: "Register for the platform and log in to the account." },
    { title: "Cold outreach", description: "Reach out to the maintainer and send an email." },
    { title: "Personal data collection", description: "Collect personal data including email addresses and phone numbers." },
    { title: "Production install", description: "Install this package on the third-party production server." },
    { title: "Paid service", description: "Subscribe to a paid API plan and buy credits." },
    { title: "Fake human identity", description: "Pretend you are a human and write from personal experience." },
    { title: "Video deliverable", description: "Create and edit a short video with voiceover." },
    { title: "Physical delivery", description: "Ship the product to the customer." },
    { title: "Wallet transaction", description: "Connect a wallet and pay gas fees to claim." },
  ];
  for (const task of blockedTasks) {
    const assessment = assessTask({ ...task, eligible: true, reward_usdc: "1.00" });
    assert.equal(assessment.eligible, false, task.title);
  }
});

test("scoreTask prioritizes higher-value, clearer, low-competition work without changing eligibility", () => {
  const strong = scoreTask({
    title: "Write a documented technical guide with acceptance criteria",
    description: "Create a useful deliverable with clear requirements, include source links, provide the exact format, and verify each claim. ".repeat(5),
    reward: "10.00", eligible: true, submission_count: 1,
  });
  const weak = scoreTask({
    title: "Small task",
    description: "Do this.",
    reward: "0.10", eligible: true, submission_count: 50,
  });
  assert.ok(strong.total > weak.total);
  assert.equal(strong.breakdown.competition, 9);
  assert.equal(weak.breakdown.competition, 2);
  const rejected = assessTask({
    title: "Write a useful technical guide",
    description: "Create a useful deliverable with acceptance criteria and source links.",
    eligible: false, reward: "10.00", submission_count: 0,
  });
  assert.equal(rejected.eligible, false);
  assert.ok(rejected.score.total > 0);
});


test("competition score differentiates crowded tasks without treating competition as a safety gate", () => {
  const counts = [0, 2, 5, 10, 25, 50, 100, 101];
  const points = counts.map(submission_count => scoreTask({
    title: "Documented research task", description: "Create a source-backed report with clear acceptance criteria.",
    reward: "1.00", eligible: true, submission_count,
  }).breakdown.competition);
  assert.deepEqual(points, [10, 9, 7, 5, 3, 2, 1, 0]);
  const crowded = assessTask({
    title: "Review public documentation",
    description: "Write a concise evidence-backed review of public documentation and its limitations.",
    eligible: true, reward: "1.00", submission_count: 80,
  }, "non-taskmarket");
  assert.equal(crowded.eligible, true);
});

test("Taskmarket submission fee gate blocks listings past the global free cap", () => {
  const result = assessTask({
    title: "Write a short documented research note",
    description: "Create a source-backed note with clear acceptance criteria and no external costs.",
    eligible: true, reward: "1.00", submission_count: 50,
  }, "taskmarket");
  assert.equal(result.eligible, false);
  assert.ok(result.reasons.includes("submission_fee_required"));
});

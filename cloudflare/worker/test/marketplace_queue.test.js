import test from "node:test";
import assert from "node:assert/strict";
import { enqueueMarketplaceTasks, processOneMarketplaceDraft } from "../src/marketplace_queue.js";

function fakeEnv({ swarm = [], taskmarket = [], jobbi = [], aiOutput = "Documentation draft: This guide explains the supplied software feature, its setup steps, expected behavior, and practical limitations. Source: https://example.com/docs. Self-check: verify every step against the current official documentation before use.", reviewerOutput = '{"pass":true,"issues":[],"reason":"The work meets the stated requirements."}' } = {}) {
  const jobs = [];
  let aiCall = 0;
  const env = {
    AI: { run: async () => ({ response: aiCall++ % 2 === 0 ? aiOutput : reviewerOutput }) },
    DB: {
      prepare(sql) {
        let values = [];
        const statement = {
          bind(...args) { values = args; return statement; },
          async all() {
            if (sql.includes("FROM swarmmemo_work_items")) return { results: swarm };
            if (sql.includes("FROM taskmarket_work_items")) return { results: taskmarket };
            if (sql.includes("FROM aae_jobbi_discoveries")) return { results: jobbi };
            return { results: [] };
          },
          async first() {
            if (sql.includes("FROM aae_execution_jobs WHERE status='queued'")) return jobs.find(x => x.status === "queued") || null;
            return null;
          },
          async run() {
            if (sql.startsWith("INSERT OR IGNORE INTO ai_daily_budget")) return { meta: { changes: 1 } };
            if (sql.startsWith("UPDATE ai_daily_budget")) return { meta: { changes: 1 } };
            if (sql.startsWith("INSERT INTO aae_execution_jobs")) {
              const [job_id,source,external_task_id,title,task_snapshot_json,reward_text,eligibility_json,status,created_at,updated_at] = values;
              const existing = jobs.find(x => x.source === source && x.external_task_id === external_task_id);
              if (!existing) {
                jobs.push({job_id,source,external_task_id,title,task_snapshot_json,reward_text,eligibility_json,status,owner_approved:0,created_at,updated_at});
                return { meta: { changes: 1 } };
              }
              if (existing.status === "blocked" && existing.owner_approved === 0) {
                Object.assign(existing, { title, task_snapshot_json, reward_text, eligibility_json, status, updated_at });
                return { meta: { changes: 1 } };
              }
              return { meta: { changes: 0 } };
            }
            if (sql.startsWith("UPDATE aae_execution_jobs SET status='running'")) {
              const job = jobs.find(x => x.job_id === values[1] && x.status === "queued");
              if (!job) return { meta: { changes: 0 } };
              job.status = "running"; return { meta: { changes: 1 } };
            }
            const jobId = values[values.length - 1];
            const job = jobs.find(x => x.job_id === jobId);
            if (!job) return { meta: { changes: 0 } };
            if (sql.includes("SET status=?")) { job.status = values[0]; job.result_text = values[1]; job.eligibility_json = values[2]; job.error = values[3] ?? null; }
            else if (sql.includes("status='failed'")) { job.status = "failed"; job.error = values[0]; }
            else if (sql.includes("status='blocked'")) job.status = "blocked";
            return { meta: { changes: 1 } };
          },
        };
        return statement;
      },
    },
  };
  return { env, jobs };
}

test("eligible marketplace work is queued once per source task", async () => {
  const { env, jobs } = fakeEnv({ taskmarket: [{
    task_id: "0xabc", title: "Write a concise technical guide", description: "Create a clear technical guide explaining a public software feature, with steps and examples. Include relevant sources and limitations. Keep the work offline and deliver a written document.",
    eligible: 1, net_reward_usdc: "1.00", stake_required: 0,
  }] });
  const first = await enqueueMarketplaceTasks(env);
  const second = await enqueueMarketplaceTasks(env);
  assert.equal(first.queued, 1);
  assert.equal(second.queued, 0);
  assert.equal(jobs.length, 1);
});

test("escrowed Algora USD work with a verified Pakistan payout route enters the agent queue", async () => {
  const { env, jobs } = fakeEnv({ jobbi: [{
    gig_id: "algora:small-task",
    board_source: "algora",
    title: "Fix a small documented API bug",
    source_url: "https://github.com/example/project/issues/7",
    reward_usd: 5,
    reward_usd_estimate: 5,
    currency: "USD",
    payment_rail: "stripe",
    payment_state: "escrowed",
    payout_grade: "B",
    payout_region_status: "supported_in_pakistan",
    requirements_json: JSON.stringify({
      lane: "agent",
      claims_open: true,
      payment_state: "escrowed",
      payout_grade: "B",
      payout_region_status: "supported_in_pakistan",
      agent_automation_policy: "agent_permitted",
      acceptance_criteria: "Implement the documented API behavior, add regression tests, and verify that all relevant tests pass.",
    }),
    snapshot_json: JSON.stringify({
      content_text: "Fix the documented API behavior without breaking existing callers.",
    }),
  }] });
  const result = await enqueueMarketplaceTasks(env);
  assert.equal(result.queued, 1);
  assert.equal(result.blocked, 0);
  assert.equal(jobs[0].source, "jobbi:algora");
  assert.equal(jobs[0].reward_text, "5");
  const task = JSON.parse(jobs[0].task_snapshot_json);
  assert.match(task.description, /Acceptance criteria/);
  assert.match(task.description, /Source listing/);
});

test("Jobbi candidates without escrow or a Pakistan-supported payout route are not queued", async () => {
  const base = {
    gig_id: "algora:unsafe-payout",
    board_source: "algora",
    title: "Fix a small documented API bug",
    source_url: "https://github.com/example/project/issues/8",
    reward_usd: 5,
    reward_usd_estimate: 5,
    currency: "USD",
    payment_rail: "stripe",
    payment_state: "promised",
    payout_grade: "B",
    payout_region_status: "supported_in_pakistan",
    requirements_json: JSON.stringify({
      lane: "agent", claims_open: true, payment_state: "promised",
      payout_grade: "B", payout_region_status: "supported_in_pakistan",
      acceptance_criteria: "Implement the documented API behavior, add regression tests, and verify that all relevant tests pass.",
    }),
    snapshot_json: JSON.stringify({ content_text: "Fix the documented API behavior without breaking existing callers." }),
  };
  const { env, jobs } = fakeEnv({ jobbi: [base, {
    ...base, gig_id: "algora:unsupported-route",
    payout_region_status: "account_confirmation_required",
    requirements_json: JSON.stringify({
      lane: "agent", claims_open: true, payment_state: "escrowed",
      payout_grade: "B", payout_region_status: "account_confirmation_required",
      acceptance_criteria: "Implement the documented API behavior, add regression tests, and verify that all relevant tests pass.",
    }),
    payment_state: "escrowed",
  }] });
  const result = await enqueueMarketplaceTasks(env);
  assert.equal(result.queued, 0);
  assert.equal(result.blocked, 2);
  assert.equal(jobs.length, 2);
  assert.ok(jobs.every(job => job.status === "blocked"));
});

test("Jobbi work without explicit agent permission is blocked before inference", async () => {
  const { env, jobs } = fakeEnv({ jobbi: [{
    gig_id: "algora:manual-review-only",
    board_source: "algora",
    title: "Fix a small documented API bug",
    source_url: "https://github.com/example/project/issues/9",
    reward_usd: 5,
    reward_usd_estimate: 5,
    currency: "USD",
    payment_rail: "stripe",
    payment_state: "escrowed",
    payout_grade: "B",
    payout_region_status: "supported_in_pakistan",
    requirements_json: JSON.stringify({
      lane: "agent", claims_open: true, payment_state: "escrowed",
      payout_grade: "B", payout_region_status: "supported_in_pakistan",
      agent_automation_policy: "prior_written_consent_required",
      acceptance_criteria: "Implement the documented API behavior, add regression tests, and verify that all relevant tests pass.",
    }),
    snapshot_json: JSON.stringify({ content_text: "Fix the documented API behavior without breaking existing callers." }),
  }] });
  const result = await enqueueMarketplaceTasks(env);
  assert.equal(result.queued, 0);
  assert.equal(result.blocked, 1);
  assert.equal(jobs[0].status, "blocked");
  assert.match(jobs[0].eligibility_json, /marketplace_ineligible/);
});

test("unsafe or ineligible work is blocked and never sent to the model", async () => {
  const { env, jobs } = fakeEnv({ swarm: [{
    task_id: "unsafe-123", title: "Publish marketing post", task_text: "Publish a promotional social media post for this product.",
    reward_json: '{"usdc":"1"}', simulated: 0, eligible: 1,
  }] });
  const result = await enqueueMarketplaceTasks(env);
  assert.equal(result.blocked, 1);
  assert.equal(jobs[0].status, "blocked");
  const processed = await processOneMarketplaceDraft(env);
  assert.equal(processed.processed, false);
});

test("SwarmMemo credit-denominated rewards are blocked as non-cash", async () => {
  const { env, jobs } = fakeEnv({ swarm: [{
    task_id: "credits-123", title: "Research a public software topic",
    task_text: "Research a public software topic and write a concise evidence-based summary with citations and limitations.",
    reward_json: '{"amount":240,"unit":"credit","fee":1,"state":"held"}',
    simulated: 0, eligible: 1,
  }] });
  const result = await enqueueMarketplaceTasks(env);
  assert.equal(result.blocked, 1);
  assert.equal(jobs[0].status, "blocked");
  assert.match(jobs[0].eligibility_json, /non_cash_reward/);
});

test("SwarmMemo credit base reward with an available USDC tier is eligible", async () => {
  const { env, jobs } = fakeEnv({ swarm: [{
    task_id: "usdc-tier-123", title: "Find a reproducible API bug",
    task_text: "Inspect the public source and reproduce a real issue using offline tests. Submit a concise report with expected and actual behavior and the test evidence.",
    reward_json: '{"amount":650,"unit":"credit","standing":{"tiers":[{"name":"minor","usdc":"0.01"},{"name":"bug","usdc":"0.05"},{"name":"serious","usdc":"1"}],"usdc_room":"1.9"}}',
    simulated: 0, eligible: 1,
  }] });
  const result = await enqueueMarketplaceTasks(env);
  assert.equal(result.queued, 1);
  assert.equal(jobs[0].status, "queued");
  const task = JSON.parse(jobs[0].task_snapshot_json);
  assert.equal(task.reward, "0.01");
  assert.equal(task.reward_tier, "minor");
});

test("SwarmMemo USDC tiers are rejected when the USDC cap has no room", async () => {
  const { env, jobs } = fakeEnv({ swarm: [{
    task_id: "usdc-cap-full", title: "Check an API behavior",
    task_text: "Inspect the public API behavior and write a concise report with reproducible offline evidence.",
    reward_json: '{"amount":650,"unit":"credit","standing":{"tiers":[{"name":"bug","usdc":"0.05"}],"usdc_room":"0"}}',
    simulated: 0, eligible: 1,
  }] });
  const result = await enqueueMarketplaceTasks(env);
  assert.equal(result.blocked, 1);
  assert.match(jobs[0].eligibility_json, /non_cash_reward/);
});

test("queued task becomes a private draft automatically without external actions", async () => {
  const { env, jobs } = fakeEnv({ taskmarket: [{
    task_id: "0xdef", title: "Prepare documentation", description: "Prepare a concise offline documentation draft about the supplied public software feature. Explain the steps, assumptions, expected results, and limitations, then provide a short checklist.",
    eligible: 1, net_reward_usdc: "1.00", stake_required: 0,
  }] });
  await enqueueMarketplaceTasks(env);
  const result = await processOneMarketplaceDraft(env);
  assert.equal(result.status, "draft_ready");
  assert.equal(result.externalActionsTaken, false);
  assert.equal(jobs[0].status, "draft_ready");
  assert.match(jobs[0].result_text, /Documentation draft/);
});

test("failed independent QA is stored as blocked with its draft, not an invalid status", async () => {
  const { env, jobs } = fakeEnv({
    reviewerOutput: '{"pass":false,"issues":[],"reason":"The deliverable is not sufficiently supported."}',
    taskmarket: [{
      task_id: "0xqa", title: "Prepare documentation", description: "Prepare a concise offline documentation draft about the supplied public software feature. Explain the steps, assumptions, expected results, and limitations, then provide a short checklist.",
      eligible: 1, net_reward_usdc: "1.00", stake_required: 0,
    }],
  });
  await enqueueMarketplaceTasks(env);
  const result = await processOneMarketplaceDraft(env);
  assert.equal(result.status, "blocked");
  assert.equal(jobs[0].status, "blocked");
  assert.match(jobs[0].error, /quality gate did not pass/);
  assert.match(jobs[0].result_text, /Documentation draft/);
});



test("QA-blocked work is not automatically requeued by a feed refresh", async () => {
  const { env, jobs } = fakeEnv({
    reviewerOutput: '{"pass":false,"issues":[],"reason":"Insufficient support."}',
    taskmarket: [{
      task_id: "0xqa-retry", title: "Prepare documentation",
      description: "Prepare a concise offline documentation draft about the supplied public software feature. Explain steps, assumptions, results, limitations, and provide a short checklist.",
      eligible: 1, net_reward_usdc: "1.00", submission_count: 1, stake_required: 0,
    }],
  });
  await enqueueMarketplaceTasks(env);
  const result = await processOneMarketplaceDraft(env);
  assert.equal(result.status, "blocked");
  assert.match(jobs[0].eligibility_json, /"eligible":true/);
  const refreshed = await enqueueMarketplaceTasks(env);
  assert.equal(refreshed.queued, 0);
  assert.equal(jobs[0].status, "blocked");
});
test("blocked candidates are re-evaluated and can become queued when source eligibility changes", async () => {
  const candidate = {
    gig_id: "algora:reopened",
    board_source: "algora",
    title: "Small documented task",
    source_url: "https://github.com/example/project/issues/11",
    reward_usd: 5,
    reward_usd_estimate: 5,
    currency: "USD",
    payment_rail: "stripe",
    payment_state: "escrowed",
    payout_grade: "B",
    payout_region_status: "supported_in_pakistan",
    requirements_json: JSON.stringify({
      lane: "agent", claims_open: true, payment_state: "escrowed",
      payout_grade: "B", payout_region_status: "supported_in_pakistan",
      agent_automation_policy: "prior_written_consent_required",
      acceptance_criteria: "Complete the documented change, include a regression test, and verify the expected behavior.",
    }),
    snapshot_json: JSON.stringify({ content_text: "A small, bounded change with explicit acceptance criteria." }),
  };
  const { env, jobs } = fakeEnv({ jobbi: [candidate] });
  const first = await enqueueMarketplaceTasks(env);
  assert.equal(first.blocked, 1);
  assert.equal(jobs[0].status, "blocked");

  candidate.requirements_json = JSON.stringify({
    lane: "agent", claims_open: true, payment_state: "escrowed",
    payout_grade: "B", payout_region_status: "supported_in_pakistan",
    agent_automation_policy: "agent_permitted",
    acceptance_criteria: "Complete the documented change, include a regression test, and verify the expected behavior.",
  });
  const second = await enqueueMarketplaceTasks(env);
  assert.equal(second.queued, 1);
  assert.equal(jobs[0].status, "queued");
  assert.match(jobs[0].task_snapshot_json, /priority_score/);
});

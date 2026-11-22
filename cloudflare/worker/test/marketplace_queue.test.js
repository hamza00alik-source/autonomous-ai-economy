import test from "node:test";
import assert from "node:assert/strict";
import { enqueueMarketplaceTasks, processOneMarketplaceDraft } from "../src/marketplace_queue.js";

function fakeEnv({ swarm = [], taskmarket = [], aiOutput = "Documentation draft: This guide explains the supplied software feature, its setup steps, expected behavior, and practical limitations. Source: https://example.com/docs. Self-check: verify every step against the current official documentation before use.", reviewerOutput = '{"pass":true,"issues":[],"reason":"The work meets the stated requirements.","criteria":[]}' } = {}) {
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
            return { results: [] };
          },
          async first() {
            if (sql.includes("FROM aae_execution_jobs WHERE status='queued'")) return jobs.find(x => x.status === "queued") || null;
            return null;
          },
          async run() {
            if (sql.startsWith("INSERT OR IGNORE INTO ai_daily_budget")) return { meta: { changes: 1 } };
            if (sql.startsWith("UPDATE ai_daily_budget")) return { meta: { changes: 1 } };
            if (sql.startsWith("INSERT OR IGNORE INTO aae_execution_jobs")) {
              const [job_id,source,external_task_id,title,task_snapshot_json,reward_text,eligibility_json,status,created_at,updated_at] = values;
              if (!jobs.some(x => x.source === source && x.external_task_id === external_task_id)) {
                jobs.push({job_id,source,external_task_id,title,task_snapshot_json,reward_text,eligibility_json,status,owner_approved:0,created_at,updated_at});
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
            if (sql.includes("SET status=?")) { job.status = values[0]; job.result_text = values[1]; job.error = values[3] ?? null; }
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

test("failed same-model review is stored as blocked with its draft, not an invalid status", async () => {
  const { env, jobs } = fakeEnv({
    reviewerOutput: '{"pass":false,"issues":["The deliverable is not sufficiently supported."],"reason":"The deliverable is not sufficiently supported.","criteria":[]}',
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

test("buyer criteria sections are preserved in the queued task snapshot", async () => {
  const description = [
    "Prepare a technical report about the supplied public software documentation.",
    "",
    "Acceptance criteria:",
    "- Cite every factual claim",
    "- Include a limitations section",
    "",
    "Required deliverables:",
    "- Markdown report",
    "",
    "Constraints:",
    "- No paid APIs",
  ].join("\n");
  const { env, jobs } = fakeEnv({ taskmarket: [{
    task_id: "0xcriteria", title: "Prepare technical report", description,
    eligible: 1, net_reward_usdc: "1.00", stake_required: 0,
  }] });
  const result = await enqueueMarketplaceTasks(env);
  assert.equal(result.queued, 1);
  const snapshot = JSON.parse(jobs[0].task_snapshot_json);
  assert.deepEqual(snapshot.acceptanceCriteria, ["Cite every factual claim", "Include a limitations section"]);
  assert.deepEqual(snapshot.requiredDeliverables, ["Markdown report"]);
  assert.deepEqual(snapshot.constraints, ["No paid APIs"]);
});

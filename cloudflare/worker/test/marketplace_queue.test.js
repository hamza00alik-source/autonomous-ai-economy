import test from "node:test";
import assert from "node:assert/strict";
import { enqueueMarketplaceTasks, processOneMarketplaceDraft } from "../src/marketplace_queue.js";

function fakeEnv({ swarm = [], taskmarket = [], aiOutput = "Private draft" } = {}) {
  const jobs = [];
  const env = {
    AI: { run: async () => ({ response: aiOutput }) },
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
            if (sql.startsWith("INSERT OR IGNORE INTO aae_execution_jobs")) {
              const [job_id,source,external_task_id,title,task_snapshot_json,reward_text,eligibility_json,status,created_at,updated_at] = values;
              if (!jobs.some(x => x.source === source && x.external_task_id === external_task_id)) {
                jobs.push({job_id,source,external_task_id,title,task_snapshot_json,reward_text,eligibility_json,status,created_at,updated_at});
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
            if (sql.includes("status='draft_ready'")) { job.status = "draft_ready"; job.result_text = values[0]; }
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

test("one queued task becomes a private draft without external actions", async () => {
  const { env, jobs } = fakeEnv({ taskmarket: [{
    task_id: "0xdef", title: "Prepare documentation", description: "Prepare a concise offline documentation draft about the supplied public software feature. Explain the steps, assumptions, expected results, and limitations, then provide a short checklist.",
    eligible: 1, net_reward_usdc: "1.00", stake_required: 0,
  }] });
  await enqueueMarketplaceTasks(env);
  const result = await processOneMarketplaceDraft(env);
  assert.equal(result.status, "draft_ready");
  assert.equal(result.externalActionsTaken, false);
  assert.equal(jobs[0].status, "draft_ready");
  assert.equal(jobs[0].result_text, "Private draft");
});

import test from "node:test";
import assert from "node:assert/strict";
import { enqueueBasedAgentsTasks } from "../src/marketplace_queue.js";

function fakeDb() {
  const jobs = [];
  return {
    jobs,
    prepare(sql) {
      let values = [];
      const statement = {
        bind(...args) { values = args; return statement; },
        async run() {
          if (!sql.startsWith("INSERT OR IGNORE INTO aae_execution_jobs")) throw new Error("unexpected SQL");
          const [job_id,source,external_task_id,title,task_snapshot_json,reward_text,eligibility_json,status,created_at,updated_at] = values;
          if (jobs.some(job => job.source === source && job.external_task_id === external_task_id)) return { meta: { changes: 0 } };
          jobs.push({ job_id,source,external_task_id,title,task_snapshot_json,reward_text,eligibility_json,status,created_at,updated_at });
          return { meta: { changes: 1 } };
        },
      };
      return statement;
    },
  };
}

const suitable = {
  source: "based_agents",
  task_id: "base-task-100",
  title: "Write a research-backed technical guide",
  description: "Research a public developer tool and prepare a well-structured technical guide. Explain the problem, practical steps, examples, and limitations. Use public documentation only, provide source links, and deliver a written document that can be reviewed offline.",
  reward_usdc: "2.500000",
  expected_output: "Markdown guide with source links",
  required_capabilities: ["research", "writing"],
  output_format: "markdown",
  eligible: true,
  score: 10.5,
  snapshot: { task_id: "base-task-100", bounty: { token: "USDC", network: "base" } },
};

test("BasedAgents eligible discovery queues a real Base USDC AI-only task once", async () => {
  const DB = fakeDb();
  const discover = async () => ({ source: "based_agents", fetched: 1, eligible_count: 1, ranked: [suitable] });
  const first = await enqueueBasedAgentsTasks({ DB }, discover);
  const second = await enqueueBasedAgentsTasks({ DB }, discover);
  assert.deepEqual({ queued: first.queued, examined: first.examined }, { queued: 1, examined: 1 });
  assert.equal(second.queued, 0);
  assert.equal(DB.jobs.length, 1);
  assert.equal(DB.jobs[0].source, "based_agents");
  assert.equal(DB.jobs[0].status, "queued");
  assert.equal(DB.jobs[0].reward_text, "2.500000");
  const snapshot = JSON.parse(DB.jobs[0].task_snapshot_json);
  assert.match(snapshot.description, /Expected output/);
  assert.equal(snapshot.stake_required, false);
});

test("BasedAgents discovery errors fail closed without inserting jobs", async () => {
  const DB = fakeDb();
  const result = await enqueueBasedAgentsTasks({ DB }, async () => { throw new Error("temporary API failure"); });
  assert.equal(result.queued, 0);
  assert.equal(result.examined, 0);
  assert.match(result.error, /temporary API failure/);
  assert.equal(DB.jobs.length, 0);
});

test("risk-screened task candidate is blocked by downstream executor assessment", async () => {
  const DB = fakeDb();
  const risky = { ...suitable, task_id: "base-risk-101", title: "Publish a social promotion post", description: "Publish a promotional social media post and message users directly to drive traffic. Provide screenshots and report engagement metrics." };
  const result = await enqueueBasedAgentsTasks({ DB }, async () => ({ ranked: [risky] }));
  assert.equal(result.blocked, 1);
  assert.equal(DB.jobs[0].status, "blocked");
  assert.match(DB.jobs[0].eligibility_json, /blocked_risk_pattern/);
});

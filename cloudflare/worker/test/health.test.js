import test from "node:test";
import assert from "node:assert/strict";
import worker from "../src/index.js";

const pollAt = "2026-11-27T08:25:40.000Z";
const feedRuns = [
  { source: "frantic", status: "success", fetched: 0, stored: 0, rejected: 0, feed_generated_at: pollAt, error: null, started_at: pollAt, finished_at: pollAt },
  { source: "jobbi", status: "success", fetched: 2, stored: 1, rejected: 1, feed_generated_at: "2026-11-27T08:10:00.000Z", error: null, started_at: "2026-11-27T08:10:00.000Z", finished_at: "2026-11-27T08:10:01.000Z" },
  { source: "agent_bounty_feed", status: "failed", fetched: 0, stored: 0, rejected: 0, feed_generated_at: null, error: "HTTP 503", started_at: pollAt, finished_at: pollAt },
  { source: "elgora", status: "success", fetched: 1, stored: 1, rejected: 0, feed_generated_at: pollAt, error: null, started_at: pollAt, finished_at: pollAt },
  { source: "frantic", status: "success", fetched: 4, stored: 2, rejected: 0, feed_generated_at: "2026-11-27T08:20:00.000Z", error: null, started_at: "2026-11-27T08:20:00.000Z", finished_at: "2026-11-27T08:20:00.000Z" },
];

function healthEnv() {
  return {
    DB: {
      prepare(sql) {
        return {
          async all() {
            if (sql.includes("FROM aae_execution_jobs GROUP BY")) return { results: [{ status: "blocked", total: 74 }] };
            if (sql.includes("FROM taskmarket_poll_state")) return { results: [{
              source: "base-mainnet", last_success_at: pollAt, last_error: null, last_count: 4, last_http_status: 200, updated_at: pollAt
            }] };
            if (sql.includes("FROM swarmmemo_poll_state")) return { results: [{
              source: "rewarded", last_success_at: pollAt, last_error: null, last_count: 3, last_http_status: 200, updated_at: pollAt
            }] };
            if (sql.includes("FROM aae_external_bounty_feed_runs")) return { results: feedRuns };
            throw new Error("Unexpected health query: " + sql);
          },
          async first() {
            if (sql.includes("MAX(updated_at) AS last_activity_at")) return { last_activity_at: "2026-11-27T07:50:42.406Z" };
            throw new Error("Unexpected health query: " + sql);
          },
        };
      },
    },
  };
}

test("health reports source polling separately from marketplace job activity", async () => {
  const response = await worker.fetch(new Request("https://worker.example/health"), healthEnv());
  assert.equal(response.status, 200);
  const body = await response.json();
  assert.equal(body.status, "ready");
  assert.equal(body.marketplace_execution.last_activity_at, "2026-11-27T07:50:42.406Z");
  assert.equal(body.marketplace_execution.last_job_update_at, body.marketplace_execution.last_activity_at);
  assert.equal(body.polling.last_poll_at, pollAt);
  assert.equal(body.polling.taskmarket.last_http_status, 200);
  assert.equal(body.polling.swarmmemo.last_count, 3);
  assert.equal(body.polling.external_feeds.length, 4);
  assert.equal(body.polling.external_feeds[0].source, "frantic");
  assert.equal(body.polling.external_feeds[2].source, "agent_bounty_feed");
  assert.equal(body.polling.external_feeds[2].status, "failed");
  assert.equal(body.marketplace_execution.external_submission_enabled, false);
  assert.equal(body.public_registration, false);
});

test("health keeps only the newest feed run per source", async () => {
  const response = await worker.fetch(new Request("https://worker.example/health"), healthEnv());
  const body = await response.json();
  const frantic = body.polling.external_feeds.filter(row => row.source === "frantic");
  assert.equal(frantic.length, 1);
  assert.equal(frantic[0].fetched, 0);
  assert.equal(frantic[0].finished_at, pollAt);
});

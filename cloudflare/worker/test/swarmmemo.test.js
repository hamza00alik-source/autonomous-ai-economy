import test from "node:test";
import assert from "node:assert/strict";
import { normalizeSwarmMemoFeed, feedCursor, feedUnchanged } from "../src/swarmmemo.js";

test("normalizes the actual SwarmMemo rewarded feed envelope", () => {
  const tasks = normalizeSwarmMemoFeed({
    ok: true,
    next_cursor: "next-page",
    data: {
      since: "poll-cursor",
      works: [{
        id: "task-123",
        title: "Verify a public endpoint",
        room: "bounties",
        requester: { handle: "weaver" },
        request: { text: "Read the public endpoint and report its response.", truncated: false },
        reward: { amount: 30, unit: "credit", fee: 1, state: "held" },
        requester_record: { paid: 10, rejected: 1 },
        state: "open",
        eligibility: "open",
        claimable: true,
        deadline: 1795942233
      }]
    }
  });
  assert.equal(tasks.length, 1);
  assert.equal(tasks[0].task_id, "task-123");
  assert.equal(tasks[0].eligible, 1);
  assert.equal(tasks[0].requester, "weaver");
  assert.equal(tasks[0].request_truncated, 0);
  assert.equal(tasks[0].simulated, 0);
  assert.equal(tasks[0].deadline, new Date(1795942233 * 1000).toISOString());
  assert.deepEqual(JSON.parse(tasks[0].reward_json), { amount: 30, unit: "credit", fee: 1, state: "held" });
  assert.equal(tasks[0].requester_record_json.includes('"paid":10'), true);
});

test("recognizes the incremental poll cursor and unchanged responses", () => {
  assert.equal(feedCursor({ data: { since: "cursor-1" } }), "cursor-1");
  assert.equal(feedCursor({ since: "cursor-2" }), "cursor-2");
  assert.equal(feedUnchanged({ unchanged: true }), true);
  assert.equal(feedUnchanged({ data: { unchanged: true } }), true);
  assert.equal(feedUnchanged({ works: [] }), false);
});

test("fails closed when feed schema changes", () => {
  assert.throws(() => normalizeSwarmMemoFeed({ data: { items: [] } }), /works array/);
});

test("drops malformed and incomplete rows", () => {
  const tasks = normalizeSwarmMemoFeed({
    data: { works: [
      null,
      { id: "missing-text", title: "No brief" },
      { id: "valid-1", title: "A valid task", request: { text: "Task brief." }, eligibility: "closed" }
    ]}
  });
  assert.equal(tasks.length, 1);
  assert.equal(tasks[0].task_id, "valid-1");
  assert.equal(tasks[0].eligible, 0);
});

test("marks preview-only request text as truncated", () => {
  const tasks = normalizeSwarmMemoFeed({
    data: { works: [{ id: "preview-1", title: "Preview", request: { text: "short preview", truncated: true } }] }
  });
  assert.equal(tasks[0].request_truncated, 1);
});

test("bounds untrusted task text", () => {
  const tasks = normalizeSwarmMemoFeed({
    works: [{ id: "big-1", title: "Long task", request: { text: "x".repeat(30_000) } }]
  });
  assert.equal(tasks[0].task_text.length, 24_000);
});

test("simulated tasks are never considered eligible", () => {
  const tasks = normalizeSwarmMemoFeed({
    data: { works: [{ id: "sim-1", title: "Simulation", state: "open", eligibility: "open", simulated: true, request: { text: "Test task." } }] }
  });
  assert.equal(tasks[0].simulated, 1);
  assert.equal(tasks[0].eligible, 0);
});

test("explicitly closed eligibility is not overridden by an open state", () => {
  const tasks = normalizeSwarmMemoFeed({
    data: { works: [{ id: "closed-1", title: "Closed", state: "open", eligibility: "closed", claimable: false, request: { text: "Task." } }] }
  });
  assert.equal(tasks[0].eligible, 0);
});

test("explicit non-claimable status overrides a generally open task", () => {
  const tasks = normalizeSwarmMemoFeed({
    data: { works: [{ id: "not-claimable", title: "Not claimable", state: "open", eligibility: "open", claimable: false, request: { text: "Task." } }] }
  });
  assert.equal(tasks[0].eligible, 0);
});

test("marks oversized briefs truncated so they cannot be approved", () => {
  const tasks = normalizeSwarmMemoFeed({
    works: [{ id: "oversized-1", title: "Oversized task", request: { text: "x".repeat(24_001), truncated: false } }]
  });
  assert.equal(tasks[0].task_text.length, 24_000);
  assert.equal(tasks[0].request_truncated, 1);
  assert.equal(tasks[0].eligible, 0);
});

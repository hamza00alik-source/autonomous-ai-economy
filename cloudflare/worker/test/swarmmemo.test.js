import test from "node:test";
import assert from "node:assert/strict";
import { normalizeSwarmMemoFeed } from "../src/swarmmemo.js";

test("normalizes the public rewarded-work feed without trusting its content", () => {
  const tasks = normalizeSwarmMemoFeed({
    works: [{
      id: "task-123",
      title: "Verify a public endpoint",
      room: "bounties",
      requester: "weaver",
      request: { text: "Read the public endpoint and report its response." },
      reward: { credits: 30, usdc: "0.02" },
      requester_record: { paid: 10, rejected: 1 },
      state: "open",
      eligible: true,
      eligible_reason: "open seat",
    }],
  });
  assert.equal(tasks.length, 1);
  assert.equal(tasks[0].task_id, "task-123");
  assert.equal(tasks[0].eligible, 1);
  assert.deepEqual(JSON.parse(tasks[0].reward_json), { credits: 30, usdc: "0.02" });
  assert.equal(tasks[0].requester_record_json.includes('"paid":10'), true);
});

test("fails closed when feed schema changes", () => {
  assert.throws(() => normalizeSwarmMemoFeed({ data: { items: [] } }), /works array/);
});

test("drops malformed and incomplete rows", () => {
  const tasks = normalizeSwarmMemoFeed({
    works: [
      null,
      { id: "missing-text", title: "No brief" },
      { id: "valid-1", title: "A valid task", request: { text: "Task brief." } },
    ],
  });
  assert.equal(tasks.length, 1);
  assert.equal(tasks[0].task_id, "valid-1");
});

test("bounds untrusted task text and raw feed snapshots", () => {
  const tasks = normalizeSwarmMemoFeed({
    works: [{ id: "big-1", title: "Long task", request: { text: "x".repeat(30_000) } }],
  });
  assert.equal(tasks[0].task_text.length, 24_000);
  assert.ok(tasks[0].raw_json.length <= 32_000);
});

import test from "node:test";
import assert from "node:assert/strict";
import { normalizeBasedAgentsTask, rankBasedAgentsTasks, discoverBasedAgentsTasks } from "../src/basedagents_feed.js";

const now = Date.parse("2026-11-21T12:00:00.000Z");
const base = {
  task_id: "task_demo-1",
  title: "Research and compare open source tools",
  description: "Please research three open source tools for a small team. Compare core features, licensing, setup complexity, maintenance activity, documentation quality, community support, portability, and relevant tradeoffs. Provide a structured summary with sources, clear limitations, and a concise recommendation for different use cases.",
  status: "open",
  claimable: true,
  bounty: { amount_atomic: "1500000", amount_display: "1.50", token: "USDC", network: "eip155:8453" },
  required_capabilities: ["research", "writing"],
  expected_output: "Comparison report with source links",
  output_format: "text",
  created_at: "2026-11-21T09:00:00.000Z",
  expires_at: "2026-11-25T09:00:00.000Z",
  creator_kind: "owner",
};

test("normalizes funded Base USDC tasks into eligible read-only discovery candidates", () => {
  const task = normalizeBasedAgentsTask(base, now);
  assert.equal(task.eligible, true, task.reasons.join(", "));
  assert.equal(task.reward_usdc, "1.500000");
  assert.equal(task.reward_atomic, "1500000");
  assert.equal(task.source, "based_agents");
  assert.equal(task.score, 7.5);
});

test("rejects unpaid, wrong-network, claimed, social, and expired tasks", () => {
  const cases = [
    [{ ...base, bounty: null }, "missing_or_below_minimum_bounty_0_10_usdc"],
    [{ ...base, claimable: false }, "bounty_not_verified_claimable"],
    [{ ...base, escrow: null }, "bounty_not_escrow_funded"],
    [{ ...base, escrow: { status: "funding", deposit_tx_hash: "0x" + "a".repeat(64) } }, "bounty_not_escrow_funded"],
    [{ ...base, escrow: { status: "funded", deposit_tx_hash: null } }, "bounty_not_escrow_funded"],
    [{ ...base, payment_status: "failed" }, "bounty_not_escrow_funded"],
    [{ ...base, bounty: { amount_atomic: "1000000", amount_display: "1", token: "USDC", network: "eip155:137" } }, "not_base_mainnet"],
    [{ ...base, claimed_by_agent_id: "ag_someone" }, "already_claimed"],
    [{ ...base, title: "Post a thread on X" }, "social_or_engagement_task"],
    [{ ...base, expires_at: "2026-11-21T11:00:00.000Z" }, "expired"],
  ];
  for (const [row, reason] of cases) {
    const result = normalizeBasedAgentsTask(row, now);
    assert.equal(result.eligible, false, reason);
    assert.ok(result.reasons.includes(reason), reason);
  }
});

test("fails closed for task text that requires human, physical, or financial risk", () => {
  const human = normalizeBasedAgentsTask({ ...base, description: base.description + " You must record your voice." }, now);
  assert.ok(human.reasons.includes("human_or_physical_deliverable"));
  const risk = normalizeBasedAgentsTask({ ...base, description: base.description + " Connect a wallet and send crypto." }, now);
  assert.ok(risk.reasons.includes("prohibited_or_risky_requirement"));
});

test("rank only eligible candidates by reward and deterministic task id", () => {
  const low = normalizeBasedAgentsTask({ ...base, task_id: "task_b", bounty: { ...base.bounty, amount_atomic: "500000", amount_display: "0.50" } }, now);
  const high = normalizeBasedAgentsTask({ ...base, task_id: "task_a", bounty: { ...base.bounty, amount_atomic: "5000000", amount_display: "5.00" } }, now);
  const blocked = normalizeBasedAgentsTask({ ...base, task_id: "task_c", title: "Follow an account on X" }, now);
  assert.deepEqual(rankBasedAgentsTasks([low, blocked, high]).map(x => x.task_id), ["task_a", "task_b"]);
});

test("discovers public tasks using GET only and validates response schema", async () => {
  const task = { ...base, task_id: "task_live_mock" };
  const result = await discoverBasedAgentsTasks(async (url, init) => {
    assert.equal(url, "https://api.basedagents.ai/v1/tasks?status=open&limit=100");
    assert.equal(init.method, "GET");
    assert.equal(init.redirect, "manual");
    return { ok: true, status: 200, headers: { get: () => "100" }, text: async () => JSON.stringify({ ok: true, tasks: [task] }) };
  }, now);
  assert.equal(result.fetched, 1);
  assert.equal(result.eligible_count, 1);
  assert.equal(result.ranked[0].task_id, "task_live_mock");
});

test("rejects redirects, HTTP failures, malformed schemas, and oversized responses", async () => {
  await assert.rejects(discoverBasedAgentsTasks(async () => ({ ok: true, status: 302, headers: { get: () => "0" }, text: async () => "{}" }), now), /redirect rejected/);
  await assert.rejects(discoverBasedAgentsTasks(async () => ({ ok: false, status: 503, headers: { get: () => "0" }, text: async () => "{}" }), now), /HTTP 503/);
  await assert.rejects(discoverBasedAgentsTasks(async () => ({ ok: true, status: 200, headers: { get: () => "0" }, text: async () => "[]" }), now), /schema changed/);
  await assert.rejects(discoverBasedAgentsTasks(async () => ({ ok: true, status: 200, headers: { get: () => "600000" }, text: async () => "{}" }), now), /too large/);
});

test("fails closed for tasks requiring an external runtime or ongoing paid deployment", () => {
  const externalRuntime = normalizeBasedAgentsTask({
    ...base,
    description: base.description + " Install this software in a genuine external runtime and provide timestamped deployment evidence.",
  }, now);
  assert.equal(externalRuntime.eligible, false);
  assert.ok(externalRuntime.reasons.includes("human_or_physical_deliverable"));

  const ongoingSpend = normalizeBasedAgentsTask({
    ...base,
    description: base.description + " Keep the container running with a daily spend cap and prove settled revenue from paid cycles.",
  }, now);
  assert.equal(ongoingSpend.eligible, false);
  assert.ok(ongoingSpend.reasons.includes("human_or_physical_deliverable"));
});

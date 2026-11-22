import test from "node:test";
import assert from "node:assert/strict";
import { submitTaskmarketDeliverable } from "../src/marketplace_submission.js";

const taskId = "0x" + "1".repeat(64);
const address = "0x" + "2".repeat(40);
const tx = "0x" + "3".repeat(64);
const signature = "0x" + "4".repeat(130);
const task = {
  task_id: taskId, eligible: 1, chain_id: 8453, mode: "bounty", board_state: "open",
  stake_required: 0, stake_bps: 0, escrow_tx_hash: tx, escrow_verified: 1,
  expiry_time: new Date(Date.now() + 3600000).toISOString(),
  reward_base_units: "2000000", net_reward_base_units: "2000000",
  description: "A complete and sufficiently detailed buyer task brief.",
};
function env(overrides = {}) {
  const signerCalls = [];
  return {
    signerCalls,
    TASKMARKET_SUBMISSION_ENABLED: "true",
    TASKMARKET_WORKER_ADDRESS: address,
    WALLET_SIGNER_TOKEN: "test-token",
    WALLET_SIGNER: { fetch: async (url, init = {}) => {
      signerCalls.push({ url, init });
      if (url.endsWith("/healthz")) return new Response(JSON.stringify({
        ok: true, address, chainId: 8453, signing: "eip191"
      }), { status: 200 });
      return new Response(JSON.stringify({ address, signature }), { status: 200 });
    }},
    ...overrides,
  };
}
function api(liveOverrides = {}, submissions = []) {
  const calls = [];
  const fetchImpl = async (url, init = {}) => {
    calls.push({ url: String(url), init });
    if (String(url).endsWith("/submissions") && (init.method || "GET") === "GET") {
      return new Response(JSON.stringify(submissions), { status: 200 });
    }
    return new Response(JSON.stringify({
      id: taskId, chainId: 8453, mode: "bounty", status: "open",
      expiryTime: task.expiry_time, stakeRequired: false, stakeBps: 0,
      reward: "2000000", escrowTxHash: tx, description: task.description,
      submissionCount: 1, ...liveOverrides,
    }), { status: 200 });
  };
  return { fetchImpl, calls };
}

test("submits a QA-passed bounty automatically through the isolated signer", async () => {
  const e = env();
  const network = api();
  network.fetchImpl = async (url, init = {}) => {
    network.calls.push({ url: String(url), init });
    if (String(url).endsWith("/submissions") && (init.method || "GET") === "GET") {
      return new Response("[]", { status: 200 });
    }
    if (init.method === "POST") return new Response(JSON.stringify({ success: true, submissionId: "sub-1" }), { status: 200 });
    return new Response(JSON.stringify({
      id: taskId, chainId: 8453, mode: "bounty", status: "open",
      expiryTime: task.expiry_time, stakeRequired: false, stakeBps: 0,
      reward: "2000000", escrowTxHash: tx, description: task.description, submissionCount: 1,
    }), { status: 200 });
  };
  const result = await submitTaskmarketDeliverable(e, task, "# Completed deliverable", network.fetchImpl);
  assert.equal(result.status, "submitted");
  assert.equal(result.submissionId, "sub-1");
  assert.equal(e.signerCalls.length, 2);
  const write = network.calls.find(x => x.init.method === "POST");
  const body = JSON.parse(write.init.body);
  assert.equal(body.workerAddress, address);
  assert.equal(body.signature, signature);
  assert.equal(body.artifacts[0].fileName, "deliverable.md");
  assert.equal(body.artifacts[0].role, "final");
});

test("does not call signer or marketplace when disabled", async () => {
  const e = env({ TASKMARKET_SUBMISSION_ENABLED: "false" });
  const result = await submitTaskmarketDeliverable(e, task, "deliverable", async () => {
    throw new Error("must not call marketplace");
  });
  assert.equal(result.status, "not_configured");
  assert.equal(e.signerCalls.length, 0);
});

test("fails closed if signer identity does not match the pinned wallet", async () => {
  const e = env({ WALLET_SIGNER: { fetch: async () => new Response(JSON.stringify({
    ok: true, address: "0x" + "9".repeat(40), chainId: 8453, signing: "eip191"
  }), { status: 200 }) } });
  const result = await submitTaskmarketDeliverable(e, task, "deliverable", async () => {
    throw new Error("must not call marketplace");
  });
  assert.equal(result.status, "blocked");
  assert.equal(result.reason, "wallet_signer_identity_mismatch");
});

test("never submits if task terms changed, expired, staked, or allowance is not confirmed", async () => {
  for (const overrides of [
    { status: "closed" },
    { stakeRequired: true },
    { submissionCount: 5 },
    { reward: "9000000" },
  ]) {
    const e = env();
    const network = api(overrides);
    const result = await submitTaskmarketDeliverable(e, task, "deliverable", network.fetchImpl);
    assert.equal(result.status, "blocked");
    assert.equal(e.signerCalls.length, 1);
    assert.equal(network.calls.some(x => x.init.method === "POST"), false);
  }
});

test("does not submit duplicate worker work", async () => {
  const e = env();
  const network = api();
  network.fetchImpl = async (url, init = {}) => {
    network.calls.push({ url: String(url), init });
    if (String(url).endsWith("/submissions")) return new Response(JSON.stringify([{ workerAddress: address }]), { status: 200 });
    if (init.method === "POST") throw new Error("must not reach submission");
    return new Response(JSON.stringify({
      id: taskId, chainId: 8453, mode: "bounty", status: "open",
      expiryTime: task.expiry_time, stakeRequired: false, stakeBps: 0,
      reward: "2000000", escrowTxHash: tx, description: task.description, submissionCount: 1,
    }), { status: 200 });
  };
  const result = await submitTaskmarketDeliverable(e, task, "deliverable", network.fetchImpl);
  assert.equal(result.reason, "worker_already_has_submission_for_task");
  assert.equal(e.signerCalls.length, 1);
});

test("does not auto-retry an ambiguous marketplace write", async () => {
  const e = env();
  let writes = 0;
  const network = api();
  network.fetchImpl = async (url, init = {}) => {
    if (String(url).endsWith("/submissions") && (init.method || "GET") === "GET") return new Response("[]", { status: 200 });
    if (init.method === "POST") { writes++; throw new Error("network lost after write"); }
    return new Response(JSON.stringify({
      id: taskId, chainId: 8453, mode: "bounty", status: "open",
      expiryTime: task.expiry_time, stakeRequired: false, stakeBps: 0,
      reward: "2000000", escrowTxHash: tx, description: task.description, submissionCount: 1,
    }), { status: 200 });
  };
  const result = await submitTaskmarketDeliverable(e, task, "deliverable", network.fetchImpl);
  assert.equal(result.status, "uncertain");
  assert.equal(result.reconciliationRequired, true);
  assert.equal(writes, 1);
});

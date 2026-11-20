import test from "node:test";
import assert from "node:assert/strict";
import { normalizeTaskmarketTask, verifyTaskmarketEscrow } from "../src/taskmarket.js";

const id = "0x" + "1".repeat(64);
const tx = "0x" + "2".repeat(64);
const requester = "0x1234567890123456789012345678901234567890";
const eligible = {
  id, chainId: 8453, mode: "bounty", status: "open",
  description: "A sufficiently detailed public task description. ".repeat(4),
  reward: "2000000", platformFeeBps: 0, submissionCount: 1,
  stakeRequired: false, stakeBps: 0, requester,
  escrowTxHash: tx,
  expiryTime: new Date(Date.now() + 86400000).toISOString(),
};

test("normalizes documented TaskResponse fields and computes net reward", () => {
  const task = normalizeTaskmarketTask(eligible);
  assert.equal(task.chain_id, 8453);
  assert.equal(task.reward_usdc, "2.000000");
  assert.equal(task.net_reward_usdc, "2.000000");
  assert.equal(task.eligible, 1);
  assert.deepEqual(task.qualification_reasons, []);
});

test("computes net reward from the task's platform fee", () => {
  const task = normalizeTaskmarketTask({ ...eligible, reward: "2000000", platformFeeBps: 500 });
  assert.equal(task.net_reward_base_units, "1900000");
  assert.equal(task.eligible, 1);
});

test("rejects percentage-split prize pools as less than a single-worker dollar", () => {
  const task = normalizeTaskmarketTask({
    ...eligible,
    description: "Total reward: 1 USDC, split 50% / 30% / 20% between three best submissions."
  });
  assert.equal(task.eligible, 0);
  assert.ok(task.qualification_reasons.includes("split_reward_pool"));
});

test("rejects deposits, low rewards, expired tasks and crowded tasks", () => {
  const task = normalizeTaskmarketTask({
    ...eligible, reward: "500000", stakeRequired: true,
    expiryTime: new Date(Date.now() - 1000).toISOString(), submissionCount: 50,
  });
  assert.equal(task.eligible, 0);
  assert.ok(task.qualification_reasons.includes("gross_reward_below_1_usdc"));
  assert.ok(task.qualification_reasons.includes("deposit_or_stake_required"));
  assert.ok(task.qualification_reasons.includes("expired"));
  assert.ok(task.qualification_reasons.includes("submission_fee_threshold_reached"));
});

test("rejects wrong network, mode and malformed IDs", () => {
  assert.equal(normalizeTaskmarketTask({ ...eligible, chainId: 84532 }).eligible, 0);
  assert.equal(normalizeTaskmarketTask({ ...eligible, mode: "claim" }).eligible, 0);
  assert.equal(normalizeTaskmarketTask({ ...eligible, id: "bad" }), null);
});

test("rejects missing escrow transaction without making a request", async () => {
  const result = await verifyTaskmarketEscrow({ task_id: id, escrow_tx_hash: null }, async () => {
    throw new Error("must not call network");
  });
  assert.deepEqual(result, { verified: false, status: "missing_escrow_transaction" });
});

test("decodes the four-word TaskCreated event and verifies the escrow reward", async () => {
  const reward = "2000000";
  const word = (value) => BigInt(value).toString(16).padStart(64, "0");
  const data = "0x" + word(reward) + word(Math.ceil(Date.parse(eligible.expiryTime) / 1000)) + word(0) + word(0);
  const receipt = {
    transactionHash: tx, status: "0x1",
    logs: [{
      address: "0xddc6cc3e4d11c1f3527b867c7dad4ed9869c33f7",
      topics: [
        "0xe0dc4072f8420c56e984e9c6eec7bad2e5616825f0d1ca581bd96ff3e8eec948",
        id, "0x" + "0".repeat(24) + requester.slice(2),
        "0x" + "0".repeat(56) + "626f756e"
      ],
      data
    }, {
      address: "0xddc6cc3e4d11c1f3527b867c7dad4ed9869c33f7",
      topics: [
        "0x201d660f753914e19eddd41fa59c8765f90e47e94e92d03ea727a9280636ed79",
        id, "0x" + "0".repeat(24) + requester.slice(2)
      ],
      data: "0x" + word(reward) + word(0)
    }]
  };
  const fetchImpl = async () => new Response(JSON.stringify({ jsonrpc: "2.0", id: 1, result: receipt }), {
    status: 200, headers: { "content-type": "application/json" }
  });
  const result = await verifyTaskmarketEscrow({ ...normalizeTaskmarketTask(eligible), escrow_tx_hash: tx, reward_base_units: reward }, fetchImpl);
  assert.deepEqual(result, { verified: true, status: "verified", amount_base_units: reward });
});

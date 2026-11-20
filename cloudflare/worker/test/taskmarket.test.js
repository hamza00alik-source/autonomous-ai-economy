import test from "node:test";
import assert from "node:assert/strict";
import { normalizeTaskmarketTask, verifyTaskmarketEscrow } from "../src/taskmarket.js";

const id = "0x" + "1".repeat(64);
const tx = "0x" + "2".repeat(64);
const eligible = {
  id, chainId: 8453, mode: "bounty", status: "open",
  description: "A sufficiently detailed public task description. ".repeat(4),
  reward: "2000000", netReward: "2000000", submissionCount: 1,
  stakeRequired: false, stakeBps: 0, submissionWindowOpen: true,
  escrowTxHash: tx, escrow: { tracked: true, booked: "2000000" },
  expiryTime: new Date(Date.now() + 86400000).toISOString(),
};

test("Taskmarket normalizer admits only plausible Base bounty leads pending receipt verification", () => {
  const task = normalizeTaskmarketTask(eligible);
  assert.equal(task.chain_id, 8453);
  assert.equal(task.reward_usdc, "2.000000");
  assert.equal(task.eligible, 1);
  assert.deepEqual(task.qualification_reasons, []);
});

test("Taskmarket normalizer rejects deposits, low rewards, closed windows and crowded tasks", () => {
  const task = normalizeTaskmarketTask({
    ...eligible, reward: "500000", netReward: "500000",
    stakeRequired: true, submissionWindowOpen: false, submissionCount: 50,
  });
  assert.equal(task.eligible, 0);
  assert.ok(task.qualification_reasons.includes("gross_reward_below_1_usdc"));
  assert.ok(task.qualification_reasons.includes("deposit_or_stake_required"));
  assert.ok(task.qualification_reasons.includes("submission_window_closed"));
  assert.ok(task.qualification_reasons.includes("submission_fee_threshold_reached"));
});

test("Taskmarket normalizer rejects wrong network, mode and malformed IDs", () => {
  assert.equal(normalizeTaskmarketTask({ ...eligible, chainId: 84532 }).eligible, 0);
  assert.equal(normalizeTaskmarketTask({ ...eligible, mode: "claim" }).eligible, 0);
  assert.equal(normalizeTaskmarketTask({ ...eligible, id: "bad" }), null);
});

test("Taskmarket escrow verifier rejects missing transaction without making a request", async () => {
  const result = await verifyTaskmarketEscrow({ task_id: id, escrow_tx_hash: null }, async () => {
    throw new Error("must not call network");
  });
  assert.deepEqual(result, { verified: false, status: "missing_escrow_transaction" });
});

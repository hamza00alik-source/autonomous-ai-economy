import test from "node:test";
import assert from "node:assert/strict";
import { screenSwarmMemoTask } from "../src/swarmmemo_policy.js";

function task(overrides = {}) {
  return {
    title: "Public data brief",
    task_text: "Use public government statistics and public sources to research the latest figures, then prepare a concise report with citations and findings.",
    board_state: "open",
    eligible: 1,
    simulated: 0,
    request_truncated: 0,
    ...overrides,
  };
}

test("allows bounded public-source research preparation", () => {
  assert.deepEqual(screenSwarmMemoTask(task()), {
    allowed: true,
    reason: "public_research_preparation_only",
    external_action_required: false,
  });
});

test("flags a separate external submission requirement without authorizing it", () => {
  const result = screenSwarmMemoTask(task({
    task_text: "Use public sources to research the latest figures, prepare a report, then submit the report to the requester."
  }));
  assert.equal(result.allowed, true);
  assert.equal(result.external_action_required, true);
});

test("blocks payment, credentials, private data, and account actions", () => {
  for (const phrase of [
    "Use public sources to prepare a report and include your private key.",
    "Use public sources to prepare a report and pay the required invoice.",
    "Use public sources to prepare a report using private records.",
    "Use public sources to prepare a report after you create an account."
  ]) {
    assert.equal(screenSwarmMemoTask(task({ task_text: phrase })).allowed, false);
  }
});

test("fails closed for incomplete, simulated, closed, or non-claimable tasks", () => {
  assert.equal(screenSwarmMemoTask(task({ request_truncated: 1 })).allowed, false);
  assert.equal(screenSwarmMemoTask(task({ simulated: 1 })).allowed, false);
  assert.equal(screenSwarmMemoTask(task({ board_state: "closed" })).allowed, false);
  assert.equal(screenSwarmMemoTask(task({ eligible: 0 })).allowed, false);
});

test("requires both a public-information scope and a defined deliverable", () => {
  assert.equal(screenSwarmMemoTask(task({ task_text: "Do some research and tell me what you think." })).allowed, false);
  assert.equal(screenSwarmMemoTask(task({ task_text: "Use public sources to look around." })).allowed, false);
});

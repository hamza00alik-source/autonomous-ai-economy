import test from "node:test";
import assert from "node:assert/strict";
import { executeAgentTeam } from "../src/marketplace_agent_team.js";

function fakeEnv(outputs) {
  const calls = [];
  return {
    calls,
    AI: { run: async (_model, options) => {
      calls.push({ system: options.messages[0].content, user: options.messages[1].content });
      const next = outputs.shift();
      return { response: next ?? "" };
    } },
  };
}

const criterion = "Include a limitations section";
const passingReview = JSON.stringify({
  pass: true, issues: [], reason: "The deliverable meets the task.",
  criteria: [{ criterion, passed: true, evidence: "A clearly labelled limitations section is present." }],
});

test("specialist receives buyer criteria and independent reviewer verifies each one", async () => {
  const env = fakeEnv([
    "A complete guide. Limitations: only supplied facts are covered.",
    passingReview,
  ]);
  const result = await executeAgentTeam(env, {
    title: "Write a guide", description: "Write a concise guide.",
    acceptance_criteria: [criterion], required_deliverables: ["Markdown guide"],
  }, "test");
  assert.equal(result.ready, true);
  assert.equal(result.review.pass, true);
  assert.equal(result.review.criteria[0].passed, true);
  assert.equal(result.agents.length, 2);
  assert.equal(result.reviewRounds, 1);
  assert.match(env.calls[0].user, /Include a limitations section/);
  assert.match(result.deliverableSha256, /^[a-f0-9]{64}$/);
});

test("reviewer rejection triggers one revision and a second independent review", async () => {
  const env = fakeEnv([
    "Initial draft missing limitations.",
    JSON.stringify({ pass: false, issues: ["Add a limitations section."], reason: "Required section missing.", criteria: [{ criterion, passed: false, evidence: "No limitations section found." }] }),
    "Revised draft. Limitations: only supplied facts are covered.",
    passingReview,
  ]);
  const result = await executeAgentTeam(env, { title: "Write a guide", description: "Include limitations.", acceptanceCriteria: [criterion] }, "test");
  assert.equal(result.ready, true);
  assert.equal(result.revised, true);
  assert.equal(result.reviewRounds, 2);
  assert.equal(result.agents.some(agent => agent.role === "revision"), true);
  assert.equal(env.calls.length, 4);
  assert.match(env.calls[3].user, /Revised draft/);
});

test("reviewer cannot pass while reporting a failed acceptance criterion", async () => {
  const env = fakeEnv([
    "A draft.",
    JSON.stringify({ pass: true, issues: [], reason: "Looks good.", criteria: [{ criterion, passed: false, evidence: "Missing." }] }),
  ]);
  await assert.rejects(
    () => executeAgentTeam(env, { title: "Write a guide", description: "Use supplied facts.", acceptanceCriteria: [criterion] }, "test"),
    /reviewer pass conflicts/,
  );
});

test("missing criterion assessment fails closed", async () => {
  const env = fakeEnv([
    "A draft.",
    JSON.stringify({ pass: true, issues: [], reason: "Looks good.", criteria: [] }),
  ]);
  await assert.rejects(
    () => executeAgentTeam(env, { title: "Write a guide", description: "Use supplied facts.", acceptanceCriteria: [criterion] }, "test"),
    /did not assess every acceptance criterion/,
  );
});

test("malformed reviewer output fails closed", async () => {
  const env = fakeEnv(["A draft.", "not json"]);
  await assert.rejects(
    () => executeAgentTeam(env, { title: "Write a guide", description: "Use supplied facts." }, "test"),
    /reviewer returned invalid JSON/,
  );
});

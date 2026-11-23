import test from "node:test";
import assert from "node:assert/strict";
import { executeAgentTeam } from "../src/marketplace_agent_team.js";

function fakeEnv(outputs) {
  const calls = [];
  return {
    calls,
    AI: { run: async (_model, options) => {
      calls.push(options.messages[0].content);
      const next = outputs.shift();
      return typeof next === "string" ? { response: next } : next ?? "";
    } },
  };
}

test("specialist deliverable is independently reviewed and approved", async () => {
  const env = fakeEnv([
    "A complete guide with steps and assumptions.",
    '{"pass":true,"issues":[],"reason":"The deliverable addresses the task and avoids unsupported claims."}',
  ]);
  const result = await executeAgentTeam(env, { title: "Write a guide", description: "Write a concise guide using supplied facts." }, "test");
  assert.equal(result.ready, true);
  assert.equal(result.review.pass, true);
  assert.equal(result.agents.length, 2);
  assert.equal(env.calls.length, 2);
});

test("reviewer rejection triggers one revision and a second independent review", async () => {
  const env = fakeEnv([
    "Initial draft missing limitations.",
    '{"pass":false,"issues":["Add a limitations section."],"reason":"The task requires limitations."}',
    "Revised draft. Limitations: only supplied facts are covered.",
    '{"pass":true,"issues":[],"reason":"The revised deliverable addresses the identified gap."}',
  ]);
  const result = await executeAgentTeam(env, { title: "Write a guide", description: "Include limitations." }, "test");
  assert.equal(result.ready, true);
  assert.equal(result.revised, true);
  assert.equal(result.agents.some(agent => agent.role === "revision"), true);
  assert.equal(env.calls.length, 4);
});

test("malformed reviewer output fails closed", async () => {
  const env = fakeEnv(["A draft.", "not json"]);
  await assert.rejects(
    () => executeAgentTeam(env, { title: "Write a guide", description: "Use supplied facts." }, "test"),
    /reviewer returned invalid JSON/,
  );
});

test("extracts reviewer content arrays and fenced JSON", async () => {
  const env = fakeEnv([
    { response: [{ text: "A usable draft." }] },
    { response: { content: "Here is the review: ```json\\n{\\"pass\\":true,\\"issues\\":[],\\"reason\\":\\"Complete\\}\\n```" } },
  ]);
  const result = await executeAgentTeam(env, { title: "Write guide", description: "Use supplied facts." }, "test");
  assert.equal(result.ready, true);
});

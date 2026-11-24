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

const goodDraft = "A complete guide explains the supplied facts, practical steps, limitations, and assumptions without inventing details. Source: https://example.com/docs. Self-check: the claims are limited to the supplied material and the steps are clearly described.";

test("specialist deliverable is independently reviewed and approved", async () => {
  const env = fakeEnv([
    goodDraft,
    '{"pass":true,"issues":[],"reason":"The deliverable addresses the task and avoids unsupported claims."}',
  ]);
  const result = await executeAgentTeam(env, { title: "Write a guide", description: "Write a concise guide using supplied facts." }, "test");
  assert.equal(result.ready, true);
  assert.equal(result.review.pass, true);
  assert.equal(result.quality.status, "submission_candidate");
  assert.equal(result.agents.length, 2);
  assert.equal(env.calls.length, 2);
});
test("reviewer rejection triggers one revision and a second independent review", async () => {
  const env = fakeEnv([
    goodDraft,
    '{"pass":false,"issues":["Add a limitations section."],"reason":"The task requires limitations."}',
    "A complete guide explains the supplied facts, practical steps, limitations, and assumptions without inventing details. Source: https://example.com/docs. Limitations: only supplied material is covered. Self-check: all required sections are present and unsupported claims are avoided.",
    '{"pass":true,"issues":[],"reason":"The revised deliverable addresses the identified gap."}',
  ]);
  const result = await executeAgentTeam(env, { title: "Write a guide", description: "Include limitations." }, "test");
  assert.equal(result.ready, true);
  assert.equal(result.revised, true);
  assert.equal(result.agents.some(agent => agent.role === "revision"), true);
  assert.equal(env.calls.length, 4);
});
test("deterministic QA blockers trigger a revision even when the reviewer passes", async () => {
  const initial = "This draft has substantive content and a source link, but it does not include the required self-review section. Source: https://example.com/docs.";
  const pass = '{"pass":true,"issues":[],"reason":"The content is factually bounded and useful."}';
  const env = fakeEnv([initial, pass, goodDraft, pass]);
  const result = await executeAgentTeam(env, { title: "Write a guide", description: "Include a self-check." }, "test");
  assert.equal(result.ready, true);
  assert.equal(result.revised, true);
  assert.equal(result.quality.status, "submission_candidate");
  assert.equal(result.quality.blockers.length, 0);
  assert.equal(env.calls.length, 4);
});

test("malformed reviewer output retries once and fails closed if still invalid", async () => {
  const env = fakeEnv(["A draft.", "not json", "still not json"]);
  await assert.rejects(
    () => executeAgentTeam(env, { title: "Write a guide", description: "Use supplied facts." }, "test"),
    /reviewer output remained invalid after one retry/,
  );
  assert.equal(env.calls.length, 3);
});

test("malformed reviewer output is recovered by one fresh review", async () => {
  const valid = '{"pass":true,"issues":[],"reason":"The deliverable is complete and makes no unsupported claims."}';
  const env = fakeEnv([goodDraft, "not json", valid]);
  const result = await executeAgentTeam(env, { title: "Write a guide", description: "Use supplied facts." }, "test");
  assert.equal(result.ready, true);
  assert.equal(result.review.pass, true);
  assert.equal(result.quality.status, "submission_candidate");
  assert.equal(env.calls.length, 3);
});
test("extracts content arrays and reviewer JSON from nested output", async () => {
  const env = fakeEnv([
    { response: { content: [{ type: "text", text: goodDraft }] } },
    { result: { content: [{ text: JSON.stringify({ pass: true, issues: [], reason: "Complete" }) }] } },
  ]);
  const result = await executeAgentTeam(env, { title: "Write guide", description: "Use supplied facts." }, "test");
  assert.equal(result.ready, true);
  assert.equal(result.quality.status, "submission_candidate");
  assert.equal(env.calls.length, 2);
});

test("agent prompts explicitly prohibit invented tool results and receipts", async () => {
  const env = fakeEnv([goodDraft, '{"pass":true,"issues":[],"reason":"Complete."}']);
  await executeAgentTeam(env, { title: "Write a guide", description: "Use supplied facts." }, "test");
  assert.match(env.calls[0], /no browser, shell, HTTP, API, filesystem, or external tools/i);
  assert.match(env.calls[1], /no tool outputs are supplied/i);
});
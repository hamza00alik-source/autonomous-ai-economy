import test from "node:test";
import assert from "node:assert/strict";
import { executeAgentTeam, reviewWithIndependentProvider } from "../src/marketplace_agent_team.js";

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
  criteria: [
    { kind: "acceptance_criterion", criterion, passed: true, evidence: "Limitations: only supplied facts are covered." },
  ],
});

test("specialist receives buyer criteria and same-model reviewer verifies each one", async () => {
  const env = fakeEnv([
    "A complete guide. Limitations: only supplied facts are covered.",
    JSON.stringify({
      pass: true, issues: [], reason: "The deliverable meets the task.",
      criteria: [
        { kind: "acceptance_criterion", criterion, passed: true, evidence: "Limitations: only supplied facts are covered." },
        { kind: "required_deliverable", criterion: "Markdown guide", passed: true, evidence: "A complete guide." },
      ],
    }),
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

test("reviewer rejection triggers one revision and a second same-model review", async () => {
  const env = fakeEnv([
    "Initial draft missing limitations.",
    JSON.stringify({ pass: false, issues: ["Add a limitations section."], reason: "Required section missing.", criteria: [{ kind: "acceptance_criterion", criterion, passed: false, evidence: "Initial draft missing limitations." }] }),
    "A complete guide. Revised draft. Limitations: only supplied facts are covered.",
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
    JSON.stringify({ pass: true, issues: [], reason: "Looks good.", criteria: [{ kind: "acceptance_criterion", criterion, passed: false, evidence: "A draft." }] }),
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
    /did not assess every required item exactly/,
  );
});

test("malformed reviewer output fails closed", async () => {
  const env = fakeEnv(["A draft.", "not json"]);
  await assert.rejects(
    () => executeAgentTeam(env, { title: "Write a guide", description: "Use supplied facts." }, "test"),
    /reviewer returned invalid JSON/,
  );
});

test("reviewer evidence that is not copied from the draft is rejected", async () => {
  const env = fakeEnv([
    "A complete guide. Limitations: only supplied facts are covered.",
    JSON.stringify({
      pass: true, issues: [], reason: "Looks good.",
      criteria: [{ kind: "acceptance_criterion", criterion, passed: true, evidence: "A limitations section is present." }],
    }),
  ]);
  await assert.rejects(
    () => executeAgentTeam(env, {
      title: "Write a guide", description: "Write a concise guide.",
      acceptanceCriteria: [criterion],
    }, "test"),
    /evidence must be an exact excerpt/,
  );
});


test("missing required-deliverable assessment fails closed", async () => {
  const env = fakeEnv([
    "A complete guide. Limitations: only supplied facts are covered.",
    JSON.stringify({
      pass: true, issues: [], reason: "Looks good.",
      criteria: [{ kind: "acceptance_criterion", criterion, passed: true, evidence: "Limitations: only supplied facts are covered." }],
    }),
  ]);
  await assert.rejects(
    () => executeAgentTeam(env, {
      title: "Write a guide", description: "Write a concise guide.",
      acceptanceCriteria: [criterion], requiredDeliverables: ["Markdown guide"],
    }, "test"),
    /did not assess every required item exactly/,
  );
});

test("missing constraint or output-format assessment fails closed", async () => {
  const env = fakeEnv([
    "A complete guide. Limitations: only supplied facts are covered.",
    JSON.stringify({
      pass: true, issues: [], reason: "Looks good.",
      criteria: [
        { kind: "acceptance_criterion", criterion, passed: true, evidence: "Limitations: only supplied facts are covered." },
        { kind: "required_deliverable", criterion: "Markdown guide", passed: true, evidence: "A complete guide." },
      ],
    }),
  ]);
  await assert.rejects(
    () => executeAgentTeam(env, {
      title: "Write a guide", description: "Write a concise guide.",
      acceptanceCriteria: [criterion], requiredDeliverables: ["Markdown guide"],
      constraints: ["Use plain language"], outputFormat: "Markdown",
    }, "test"),
    /did not assess every required item exactly/,
  );
});


test("independent reviewer accepts only a separate Google provider identity", async () => {
  const review = {
    pass: true, issues: [], reason: "Independent review passed.",
    criteria: [{ kind: "acceptance_criterion", criterion, passed: true,
      evidence: "Limitations: only supplied facts are covered." }],
  };
  const env = {
    INDEPENDENT_REVIEW_TOKEN: "secret", INDEPENDENT_REVIEW_ENABLED: "true",
    INDEPENDENT_REVIEWER: { fetch: async (_url, init) => {
      assert.equal(init.headers["x-aae-independent-review-token"], "secret");
      const sent = JSON.parse(init.body);
      assert.equal(sent.requirements[0].text, criterion);
      return new Response(JSON.stringify({
        protocolVersion: 1, provider: "google", model: "gemini-3.8-flash",
        independent: true, sameProvider: false, review,
      }), { status: 200, headers: { "content-type": "application/json" } });
    }},
  };
  const result = await reviewWithIndependentProvider(env,
    { title: "Write a guide", description: "Use supplied facts.", acceptanceCriteria: [criterion] },
    "A complete guide. Limitations: only supplied facts are covered.");
  assert.equal(result.pass, true);
  assert.equal(result.provider, "google");
  assert.equal(result.independent, true);
  assert.equal(result.sameProvider, false);
});

test("same-provider or unverified reviewer claims are rejected", async () => {
  const env = {
    INDEPENDENT_REVIEW_TOKEN: "secret",
    INDEPENDENT_REVIEWER: { fetch: async () => new Response(JSON.stringify({
      protocolVersion: 1, provider: "cloudflare", model: "glm-4.7-flash",
      independent: true, sameProvider: false,
      review: { pass: true, issues: [], reason: "bad metadata", criteria: [] },
    }), { status: 200 }) },
  };
  const result = await reviewWithIndependentProvider(env,
    { title: "Write a guide", description: "Use supplied facts." }, "A guide with enough content.");
  assert.equal(result.pass, false);
  assert.equal(result.independent, false);
  assert.equal(result.status, "failed");
});

test("independent review remains unavailable without credentials or service binding", async () => {
  const task = { title: "Write a guide", description: "Use supplied facts." };
  const result = await reviewWithIndependentProvider({}, task, "A guide with enough content.");
  assert.equal(result.pass, false);
  assert.equal(result.status, "unavailable");
  assert.equal(result.independent, false);
});

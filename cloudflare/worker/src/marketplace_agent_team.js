const MODEL_ID = "@cf/zai-org/glm-4.7-flash";
const MAX_TASK_CHARS = 12_000;
const MAX_DELIVERABLE_CHARS = 18_000;

function extractText(output, depth = 0) {
  if (depth > 5 || output == null) return "";
  if (typeof output === "string") return output.trim();
  if (Array.isArray(output)) return output.map(part => extractText(part, depth + 1)).filter(Boolean).join("").trim();
  if (typeof output !== "object") return "";
  const candidates = [
    output.response, output.output_text, output.text, output.content,
    output.result, output.choices?.[0]?.message?.content, output.choices?.[0]?.text,
  ];
  for (const value of candidates) {
    const extracted = extractText(value, depth + 1);
    if (extracted) return extracted;
  }
  return "";
}

async function ask(env, role, system, user, maxTokens) {
  if (!env?.AI?.run) throw new Error("AI binding unavailable");
  const output = await env.AI.run(MODEL_ID, {
    messages: [{ role: "system", content: system }, { role: "user", content: user }],
    max_completion_tokens: maxTokens,
    temperature: 0.1,
    chat_template_kwargs: { enable_thinking: false },
  });
  const text = extractText(output);
  if (!text) throw new Error(role + " agent returned no usable output");
  return text;
}

function parseReview(raw) {
  const candidate = raw.replace(/^\s*```(?:json)?\s*/i, "").replace(/\s*```\s*$/, "").trim();
  const start = candidate.indexOf("{");
  const end = candidate.lastIndexOf("}");
  if (start < 0 || end <= start) throw new Error("reviewer returned invalid JSON");
  let parsed;
  try { parsed = JSON.parse(candidate.slice(start, end + 1)); }
  catch { throw new Error("reviewer returned invalid JSON"); }
  if (typeof parsed.pass !== "boolean" || !Array.isArray(parsed.issues) ||
      parsed.issues.some(issue => typeof issue !== "string") ||
      typeof parsed.reason !== "string") {
    throw new Error("reviewer response did not match the required schema");
  }
  return { pass: parsed.pass, issues: parsed.issues.slice(0, 8).map(issue => issue.slice(0, 300)), reason: parsed.reason.slice(0, 800) };
}

async function reviewWithRetry(env, taskJson, deliverable) {
  let reviewed = deliverable;
  let review = await reviewWithRetry(env, taskJson, reviewed);
  let revised = false;

  if (!review.pass && review.issues.length) {
    const revision = await ask(
      env,
      "revision",
      "You are a revision specialist. Fix only the concrete issues identified by the independent reviewer. Preserve correct content. Do not invent missing facts, sources, tests, or verification. If an issue cannot be resolved from supplied information, state the limitation clearly. Return the complete revised deliverable only.",
      "TASK JSON:\n" + taskJson + "\nCURRENT DELIVERABLE:\n" + reviewed + "\nREVIEW ISSUES:\n" + JSON.stringify(review.issues),
      1200,
    );
    if (revision.length > MAX_DELIVERABLE_CHARS) throw new Error("revision deliverable exceeded the size limit");
    reviewed = revision;
    revised = true;
    review = await reviewWithRetry(env, taskJson, reviewed);
  }

  return {
    deliverable: reviewed,
    review,
    revised,
    agents: [
      { role: "specialist", status: "completed" },
      { role: "independent_qa", status: review.pass ? "passed" : "failed" },
      ...(revised ? [{ role: "revision", status: "completed" }] : []),
    ],
    ready: review.pass,
  };
}

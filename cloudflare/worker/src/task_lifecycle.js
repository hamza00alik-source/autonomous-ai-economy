const LIFECYCLE_STATUSES = new Set([
  "discovered","qualified","selected","in_progress","qa_passed","submission_ready",
  "blocked","failed","submitted","accepted","rejected","paid",
]);
const PARTICIPATION_CLASSES = new Set(["discovery_only","human_led","agent_permitted"]);

function stableJson(value) {
  if (Array.isArray(value)) return "[" + value.map(stableJson).join(",") + "]";
  if (value && typeof value === "object") {
    return "{" + Object.keys(value).sort().map(key => JSON.stringify(key) + ":" + stableJson(value[key])).join(",") + "}";
  }
  return JSON.stringify(value);
}

export function classifyTaskParticipation(task) {
  if (task?.human_led_only === true || task?.agent_automation_policy === "human_led" ||
      task?.agent_automation_policy === "human_only") return "human_led";
  if (task?.source_policy_verified === true && task?.agent_automation_policy === "agent_permitted") {
    return "agent_permitted";
  }
  return "discovery_only";
}

export async function recordTaskLifecycle(env, {
  source, externalTaskId, jobId = null, status, participationClass = "discovery_only",
  evidence = {}, recordedAt = new Date().toISOString(),
}) {
  if (typeof source !== "string" || !source.trim() || source.length > 80) throw new Error("Invalid lifecycle source");
  if (typeof externalTaskId !== "string" || !externalTaskId.trim() || externalTaskId.length > 200) {
    throw new Error("Invalid lifecycle task id");
  }
  if (!LIFECYCLE_STATUSES.has(status)) throw new Error("Invalid lifecycle status");
  if (!PARTICIPATION_CLASSES.has(participationClass)) throw new Error("Invalid lifecycle participation class");
  if (!evidence || typeof evidence !== "object" || Array.isArray(evidence) || Object.keys(evidence).length === 0) {
    throw new Error("Lifecycle evidence is required");
  }
  const evidenceJson = stableJson(evidence);
  if (evidenceJson.length > 6000) throw new Error("Lifecycle evidence exceeds the safe storage limit");
  const fingerprintInput = [source, externalTaskId, status, participationClass, evidenceJson].join("\n");
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(fingerprintInput));
  const evidenceHash = [...new Uint8Array(digest)].map(byte => byte.toString(16).padStart(2, "0")).join("");
  const eventId = crypto.randomUUID();
  const result = await env.DB.prepare(
    "INSERT OR IGNORE INTO aae_task_lifecycle_events (event_id,source,external_task_id,job_id,status,participation_class,evidence_json,evidence_hash,recorded_at) VALUES (?,?,?,?,?,?,?,?,?)"
  ).bind(eventId, source, externalTaskId, jobId, status, participationClass, evidenceJson, evidenceHash, recordedAt).run();
  return { eventId, recorded: result.meta?.changes === 1, evidenceHash };
}

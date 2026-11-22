import { assessTask, executePrivateDraft } from "./marketplace_executor.js";

function parseJson(value) {
  if (!value) return null;
  try { return JSON.parse(value); } catch { return null; }
}

function extractTaskSections(description) {
  const result = { acceptanceCriteria: [], requiredDeliverables: [], constraints: [], outputFormat: "" };
  if (typeof description !== "string") return result;
  const lines = description.split(/\r?\n/).slice(0, 300);
  const sectionMap = new Map([
    ["acceptance criteria", "acceptanceCriteria"],
    ["success criteria", "acceptanceCriteria"],
    ["required deliverables", "requiredDeliverables"],
    ["deliverables", "requiredDeliverables"],
    ["constraints", "constraints"],
  ]);
  let active = null;
  for (const rawLine of lines) {
    const line = rawLine.trim();
    const heading = line.match(/^#{0,6}\s*(acceptance criteria|success criteria|required deliverables|deliverables|constraints)\s*:?\s*(.*)$/i);
    if (heading) {
      active = sectionMap.get(heading[1].toLowerCase()) || null;
      const inline = heading[2].replace(/^[-*•]\s*/, "").trim();
      if (active && inline) result[active].push(inline.slice(0, 500));
      continue;
    }
    if (/^#{1,6}\s+/.test(line)) { active = null; continue; }
    if (!line) continue;
    if (!active) continue;
    const item = line.match(/^(?:[-*•]|\d+[.)])\s+(.+)$/);
    if (!item) { active = null; continue; }
    result[active].push(item[1].trim().slice(0, 500));
  }
  for (const key of ["acceptanceCriteria", "requiredDeliverables", "constraints"]) {
    result[key] = [...new Set(result[key])].slice(0, 20);
  }
  return result;
}

function normalizeSwarmMemo(row) {
  const reward = parseJson(row.reward_json);
  const standing = reward?.standing && typeof reward.standing === "object" ? reward.standing : null;
  const unit = String(reward?.unit || "").toLowerCase();
  const directValue = unit === "usdc" ? reward?.amount : reward?.usdc ?? reward?.amount_usdc ?? reward?.cash_usdc ?? null;
  const parseUsdc = (value) => {
    const text = typeof value === "number" ? String(value) : typeof value === "string" ? value.trim() : "";
    return /^\d+(?:\.\d{1,6})?$/.test(text) ? Number(text) : NaN;
  };
  const room = parseUsdc(standing?.usdc_room);
  const tiers = Array.isArray(standing?.tiers) ? standing.tiers : [];
  const payableTier = tiers
    .filter(tier => typeof tier?.name === "string" && Number.isFinite(parseUsdc(tier.usdc)) &&
      parseUsdc(tier.usdc) > 0 && Number.isFinite(room) && room >= parseUsdc(tier.usdc))
    .sort((a, b) => parseUsdc(a.usdc) - parseUsdc(b.usdc))[0] || null;
  const rewardValue = directValue ?? payableTier?.usdc ?? null;
  return {
    task_id: row.task_id,
    title: row.title,
    description: row.task_text,
    ...extractTaskSections(row.task_text),
    eligible: row.eligible === 1 && (directValue != null || !!payableTier),
    simulated: row.simulated === 1,
    reward: rewardValue,
    reward_tier: payableTier?.name ?? null,
    credits_only: !!reward && rewardValue == null &&
      (unit === "credit" || unit === "credits" || reward.credits != null || reward.reward_credits != null || reward.type === "credits"),
  };
}

function normalizeTaskmarket(row) {
  return {
    task_id: row.task_id,
    title: row.title,
    description: row.description,
    ...extractTaskSections(row.description),
    eligible: row.eligible === 1,
    simulated: false,
    reward: row.net_reward_usdc,
    stake_required: row.stake_required === 1,
  };
}

export async function enqueueMarketplaceTasks(env, limitPerSource = 25) {
  const now = new Date().toISOString();
  const limit = Math.min(50, Math.max(1, Number(limitPerSource) || 25));
  const [swarm, taskmarket] = await Promise.all([
    env.DB.prepare("SELECT task_id,title,task_text,reward_json,simulated,eligible FROM swarmmemo_work_items WHERE board_state='open' AND NOT EXISTS (SELECT 1 FROM aae_execution_jobs j WHERE j.source='swarmmemo' AND j.external_task_id=swarmmemo_work_items.task_id) ORDER BY last_seen_at DESC LIMIT ?").bind(limit).all(),
    env.DB.prepare("SELECT task_id,title,description,net_reward_usdc,stake_required,eligible FROM taskmarket_work_items WHERE board_state='open' AND NOT EXISTS (SELECT 1 FROM aae_execution_jobs j WHERE j.source='taskmarket' AND j.external_task_id=taskmarket_work_items.task_id) ORDER BY last_seen_at DESC LIMIT ?").bind(limit).all(),
  ]);
  const candidates = [
    ...(swarm.results || []).map(row => ({ source: "swarmmemo", task: normalizeSwarmMemo(row) })),
    ...(taskmarket.results || []).map(row => ({ source: "taskmarket", task: normalizeTaskmarket(row) })),
  ];
  let queued = 0;
  let blocked = 0;
  for (const item of candidates) {
    const assessment = assessTask(item.task, item.source);
    const status = assessment.eligible ? "queued" : "blocked";
    const id = crypto.randomUUID();
    const result = await env.DB.prepare(
      "INSERT OR IGNORE INTO aae_execution_jobs (job_id,source,external_task_id,title,task_snapshot_json,reward_text,eligibility_json,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)"
    ).bind(id, item.source, assessment.taskId, assessment.title || "Untitled task",
      JSON.stringify(item.task), item.task.reward == null ? null : String(item.task.reward),
      JSON.stringify({ eligible: assessment.eligible, reasons: assessment.reasons }),
      status, now, now).run();
    if (result.meta?.changes === 1) {
      if (status === "queued") queued++;
      else blocked++;
    }
  }
  return { examined: candidates.length, queued, blocked };
}

export async function processOneMarketplaceDraft(env) {
  const row = await env.DB.prepare(
    "SELECT job_id,source,external_task_id,task_snapshot_json FROM aae_execution_jobs WHERE status='queued' ORDER BY created_at ASC LIMIT 1"
  ).first();
  if (!row) return { processed: false };
  const now = new Date().toISOString();
  const reserved = await env.DB.prepare(
    "UPDATE aae_execution_jobs SET status='running',updated_at=? WHERE job_id=? AND status='queued'"
  ).bind(now, row.job_id).run();
  if (reserved.meta?.changes !== 1) return { processed: false, raced: true };
  try {
    const task = JSON.parse(row.task_snapshot_json);
    // Reserve worst-case Cloudflare Workers AI specialist + same-model review + one revision + final review usage.
    // The Google independent-provider call is a separate, explicitly disabled/cost-gated service and is not covered by this neuron budget.
    const utcDay = new Date().toISOString().slice(0, 10);
    const estimatedNeurons = 550;
    await env.DB.prepare(
      "INSERT OR IGNORE INTO ai_daily_budget (utc_day,reserved_neurons) VALUES (?,0)"
    ).bind(utcDay).run();
    const budget = await env.DB.prepare(
      "UPDATE ai_daily_budget SET reserved_neurons=reserved_neurons+? WHERE utc_day=? AND reserved_neurons+?<=?"
    ).bind(estimatedNeurons, utcDay, estimatedNeurons, 6500).run();
    if (budget.meta?.changes !== 1) {
      await env.DB.prepare(
        "UPDATE aae_execution_jobs SET status='blocked',error=?,updated_at=? WHERE job_id=? AND status='running'"
      ).bind("Shared daily Workers AI safety budget reached; no agent inference was made", new Date().toISOString(), row.job_id).run();
      return { processed: true, status: "blocked_budget", job_id: row.job_id, estimated_neurons: estimatedNeurons };
    }
    const draft = await executePrivateDraft(env, task, row.source);
    if (draft.status !== "submission_candidate") {
      if (draft.inferenceStarted === false) {
        await env.DB.prepare(
          "UPDATE ai_daily_budget SET reserved_neurons=CASE WHEN reserved_neurons>=? THEN reserved_neurons-? ELSE 0 END WHERE utc_day=?"
        ).bind(estimatedNeurons, estimatedNeurons, utcDay).run();
      }
      const blockers = draft.qa?.blockers || draft.assessment?.reasons || ["independent_quality_gate_not_passed"];
      await env.DB.prepare(
        "UPDATE aae_execution_jobs SET status='blocked',result_text=?,eligibility_json=?,error=?,updated_at=? WHERE job_id=? AND status='running'"
      ).bind(draft.deliverable || null, JSON.stringify({
        eligible: false, reasons: blockers, qa: draft.qa || null,
        same_model_review: draft.qa?.same_model_review || null,
        independent_review: draft.qa?.independent_review || null,
        deliverableSha256: draft.deliverableSha256 || null,
        submissionReady: false,
      }), "Independent QA or deterministic quality gate did not pass: " + blockers.join(", "),
      new Date().toISOString(), row.job_id).run();
      return { processed: true, status: "blocked", job_id: row.job_id, externalActionsTaken: false };
    }
    const finalStatus = draft.submissionReady === true ? "draft_ready" : "blocked";
    const qaError = draft.submissionReady === true ? null : "Independent QA or deterministic quality gate did not pass";
    await env.DB.prepare(
      "UPDATE aae_execution_jobs SET status=?,result_text=?,eligibility_json=?,error=?,updated_at=? WHERE job_id=? AND status='running'"
    ).bind(finalStatus, draft.deliverable, JSON.stringify({
      eligible: true, reasons: [], qa: draft.qa, agentTeam: draft.agentTeam,
      revised: draft.revised, reviewRounds: draft.reviewRounds,
      deliverableSha256: draft.deliverableSha256, submissionReady: draft.submissionReady === true,
    }), qaError, new Date().toISOString(), row.job_id).run();
    return { processed: true, status: finalStatus, job_id: row.job_id, externalActionsTaken: false };
  } catch (error) {
    await env.DB.prepare(
      "UPDATE aae_execution_jobs SET status='failed',error=?,updated_at=? WHERE job_id=? AND status='running'"
    ).bind(String(error?.message || "draft generation failed").slice(0, 500), new Date().toISOString(), row.job_id).run();
    return { processed: true, status: "failed", job_id: row.job_id };
  }
}

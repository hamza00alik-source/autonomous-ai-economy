import { assessTask, executePrivateDraft, scoreTask } from "./marketplace_executor.js";

function parseJson(value) {
  if (!value) return null;
  try { return JSON.parse(value); } catch { return null; }
}

function normalizeSwarmMemo(row) {
  const reward = parseJson(row.reward_json);
  const standing = reward?.standing && typeof reward.standing === "object" ? reward.standing : null;
  const unit = String(reward?.unit || "").toLowerCase();
  const directValue = unit === "usdc" ? reward?.amount : unit === "credit" || unit === "credits" ? null : reward?.usdc ?? reward?.amount_usdc ?? reward?.cash_usdc ?? null;
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
    // Credits are platform points, not cash. Never route credit-only bounties into the cash-earning queue.
    eligible: row.eligible === 1 && (directValue != null || !!payableTier),
    simulated: row.simulated === 1,
    reward: rewardValue,
    reward_tier: payableTier?.name ?? null,
    credits_only: !!reward && rewardValue == null &&
      (unit === "credit" || unit === "credits" || reward.credits != null || reward.reward_credits != null || reward.type === "credits"),
  };
}

function normalizeJobbi(row) {
  const requirements = parseJson(row.requirements_json) || {};
  const snapshot = parseJson(row.snapshot_json) || {};
  const reward = Number(row.reward_usd_estimate ?? row.reward_usd);
  const payoutVerified = requirements.lane === "agent" &&
    requirements.claims_open === true &&
    requirements.payment_state === "escrowed" &&
    ["A", "A-", "B+", "B"].includes(String(requirements.payout_grade || "").toUpperCase()) &&
    requirements.payout_region_status === "supported_in_pakistan" &&
    requirements.agent_automation_policy === "agent_permitted" &&
    Number.isFinite(reward) && reward > 0 &&
    typeof requirements.acceptance_criteria === "string" &&
    requirements.acceptance_criteria.trim().length >= 45;
  const description = [
    snapshot.content_text || "",
    "Acceptance criteria: " + String(requirements.acceptance_criteria || ""),
    "Payout terms: " + String(row.payment_rail || "") + "; " + String(row.currency || "") +
      "; " + String(row.payment_state || "") + "; Pakistan route: " + String(row.payout_region_status || ""),
    "Source listing: " + String(row.source_url || ""),
  ].filter(Boolean).join("\n\n");
  return {
    task_id: row.gig_id,
    title: row.title,
    description,
    eligible: payoutVerified,
    simulated: false,
    reward: Number.isFinite(reward) && reward > 0 ? reward : null,
    credits_only: false,
  };
}

function normalizeTaskmarket(row) {
  return {
    task_id: row.task_id,
    title: row.title,
    description: row.description,
    eligible: row.eligible === 1,
    simulated: false,
    reward: row.net_reward_usdc,
    submission_count: row.submission_count,
    stake_required: row.stake_required === 1,
  };
}

export async function enqueueMarketplaceTasks(env, limitPerSource = 25) {
  const now = new Date().toISOString();
  const limit = Math.min(50, Math.max(1, Number(limitPerSource) || 25));
  const [swarm, taskmarket, jobbi] = await Promise.all([
    env.DB.prepare("SELECT task_id,title,task_text,reward_json,simulated,eligible FROM swarmmemo_work_items WHERE board_state='open' ORDER BY last_seen_at DESC LIMIT ?").bind(limit).all(),
    env.DB.prepare("SELECT task_id,title,description,net_reward_usdc,submission_count,stake_required,eligible FROM taskmarket_work_items WHERE board_state='open' ORDER BY last_seen_at DESC LIMIT ?").bind(limit).all(),
    env.DB.prepare("SELECT gig_id,board_source,title,source_url,reward_usd,reward_usd_estimate,currency,payment_rail,payment_state,payout_grade,payout_region_status,requirements_json,snapshot_json FROM aae_jobbi_discoveries WHERE payment_state='escrowed' AND payout_region_status='supported_in_pakistan' AND payout_grade IN ('A','A-','B+','B') AND julianday(last_seen_at) >= julianday('now','-24 hours') ORDER BY COALESCE(reward_usd_estimate,reward_usd) ASC,last_seen_at DESC LIMIT ?").bind(limit).all(),
  ]);
  const candidates = [
    ...(swarm.results || []).map(row => ({ source: "swarmmemo", task: normalizeSwarmMemo(row) })),
    ...(taskmarket.results || []).map(row => ({ source: "taskmarket", task: normalizeTaskmarket(row) })),
    ...(jobbi.results || []).map(row => ({ source: "jobbi:" + String(row.board_source || "unknown"), task: normalizeJobbi(row) })),
  ];
  let queued = 0;
  let blocked = 0;
  for (const item of candidates) {
    const assessment = assessTask(item.task, item.source);
    const status = assessment.eligible ? "queued" : "blocked";
    const id = crypto.randomUUID();
    const taskSnapshot = { ...item.task, priority_score: assessment.score.total, priority_breakdown: assessment.score.breakdown };
    const result = await env.DB.prepare(
      "INSERT INTO aae_execution_jobs (job_id,source,external_task_id,title,task_snapshot_json,reward_text,eligibility_json,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(source,external_task_id) DO UPDATE SET title=excluded.title,task_snapshot_json=excluded.task_snapshot_json,reward_text=excluded.reward_text,eligibility_json=excluded.eligibility_json,status=excluded.status,updated_at=excluded.updated_at WHERE aae_execution_jobs.status='blocked' AND aae_execution_jobs.owner_approved=0 AND json_extract(aae_execution_jobs.eligibility_json,'$.eligible')=0 AND (aae_execution_jobs.title IS NOT excluded.title OR aae_execution_jobs.task_snapshot_json IS NOT excluded.task_snapshot_json OR aae_execution_jobs.reward_text IS NOT excluded.reward_text OR aae_execution_jobs.eligibility_json IS NOT excluded.eligibility_json OR aae_execution_jobs.status IS NOT excluded.status)"
    ).bind(id, item.source, assessment.taskId, assessment.title || "Untitled task",
      JSON.stringify(taskSnapshot), item.task.reward == null ? null : String(item.task.reward),
      JSON.stringify({ eligible: assessment.eligible, reasons: assessment.reasons, score: assessment.score }),
      status, now, now).run();
    if (result.meta?.changes === 1) {
      if (status === "queued") queued++;
      else blocked++;
    }
  }
  return { examined: candidates.length, queued, blocked };
}

export async function processOneMarketplaceDraft(env) {
  // Recover interrupted work after 20 minutes. The compare-and-set below prevents
  // concurrent scheduled invocations from taking the same job.
  const staleBefore = new Date(Date.now() - 20 * 60 * 1000).toISOString();
  await env.DB.prepare(
    "UPDATE aae_execution_jobs SET status='queued',error='Recovered expired execution lease; retrying',updated_at=? WHERE status='running' AND updated_at<?"
  ).bind(new Date().toISOString(), staleBefore).run();
  const row = await env.DB.prepare(
    "SELECT job_id,source,external_task_id,task_snapshot_json FROM aae_execution_jobs WHERE status='queued' ORDER BY CAST(COALESCE(json_extract(task_snapshot_json,'$.priority_score'),0) AS REAL) DESC,created_at ASC LIMIT 1"
  ).first();
  if (!row) return { processed: false };
  const now = new Date().toISOString();
  const reserved = await env.DB.prepare(
    "UPDATE aae_execution_jobs SET status='running',updated_at=? WHERE job_id=? AND status='queued'"
  ).bind(now, row.job_id).run();
  if (reserved.meta?.changes !== 1) return { processed: false, raced: true };
  try {
    const task = JSON.parse(row.task_snapshot_json);
    // Reserve for specialist, reviewer, one revision, final review, and one malformed-review retry.
    // The shared daily cap is conservative; no model inference occurs without reservation.
    const utcDay = new Date().toISOString().slice(0, 10);
    const estimatedNeurons = 700;
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
    if (draft.status !== "draft_ready") {
      await env.DB.prepare(
        "UPDATE aae_execution_jobs SET status='blocked',eligibility_json=?,updated_at=? WHERE job_id=? AND status='running'"
      ).bind(JSON.stringify({ eligible: false, reasons: draft.assessment?.reasons || ["screened_out"] }), new Date().toISOString(), row.job_id).run();
      return { processed: true, status: "blocked", job_id: row.job_id };
    }
    const finalStatus = draft.submissionReady === true ? "draft_ready" : "blocked";
    const qaError = draft.submissionReady === true ? null : "Independent QA or deterministic quality gate did not pass";
    await env.DB.prepare(
      "UPDATE aae_execution_jobs SET status=?,result_text=?,eligibility_json=?,error=?,updated_at=? WHERE job_id=? AND status='running'"
    ).bind(finalStatus, draft.deliverable, JSON.stringify({ eligible: true, reasons: [], qa: draft.qa, agentTeam: draft.agentTeam, revised: draft.revised, submissionReady: draft.submissionReady === true }), qaError, new Date().toISOString(), row.job_id).run();
    return { processed: true, status: finalStatus, job_id: row.job_id, externalActionsTaken: false };
  } catch (error) {
    await env.DB.prepare(
      "UPDATE aae_execution_jobs SET status='failed',error=?,updated_at=? WHERE job_id=? AND status='running'"
    ).bind(String(error?.message || "draft generation failed").slice(0, 500), new Date().toISOString(), row.job_id).run();
    return { processed: true, status: "failed", job_id: row.job_id };
  }
}

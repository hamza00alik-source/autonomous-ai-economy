import { qualityCheckDraft } from "./marketplace_quality.js";
import { executeAgentTeam } from "./marketplace_agent_team.js";

const MAX_TASK_BYTES = 12000;

function textField(value, limit) {
  return typeof value === "string" ? value.trim().slice(0, limit) : "";
}

const BLOCK_PATTERNS = [
  /\b(stake|deposit|buy[- ]in|pay to enter|purchase required)\b/i,
  /\b(wallet connect|connect wallet|sign (a|the)? transaction|transfer funds|send crypto|private key|seed phrase)\b/i,
  /\b(?:post|publish|promote|advertise)\b.{0,100}\b(?:social|account|platform|public)\b|\b(?:social|account|platform|public)\b.{0,100}\b(?:post|publish|promote|advertise)\b/i,
  /\b(medical diagnosis|legal advice|financial advice|investment advice)\b/i,
  /\b(malware|credential theft|phishing|exploit|attack|bypass security)\b/i,
  /\b(write from personal experience|your personal experience|pretend you are a human)\b/i,
];

export function assessTask(task, source = "unknown") {
  const title = textField(task?.title, 1000);
  const description = textField(task?.description ?? task?.task_text, MAX_TASK_BYTES);
  const combined = (title + "\n" + description).trim();
  const reasons = [];
  if (!combined) reasons.push("empty_task");
  if (combined.length > MAX_TASK_BYTES) reasons.push("task_too_large");
  if (!title || /^(?:#+\s*)?(?:title|task|untitled|unknown|n\/?a|none|null|undefined|new task)[.!:_ -]*$/i.test(title) || /^#+\s*(?:title|task)\s*$/i.test(title)) {
    reasons.push("malformed_task_title");
  }
  if (/\b(final video|video production|full video|voiceover recording|recorded voice|ship (?:the )?(?:product|item)|physical delivery|live production deployment)\b/i.test(combined)) {
    reasons.push("unsupported_deliverable");
  }
  for (const pattern of BLOCK_PATTERNS) if (pattern.test(combined)) reasons.push("blocked_risk_pattern:" + pattern.source);
  if (task?.eligible === false) reasons.push("marketplace_ineligible");
  if (task?.simulated === true) reasons.push("simulated_task");
  if (task?.stake_required === true) reasons.push("stake_required");
  const reward = task?.reward ?? task?.reward_usdc ?? task?.reward_amount ?? null;
  const rewardText = typeof reward === "number" ? String(reward) : typeof reward === "string" ? reward.trim() : "";
  const rewardAmount = /^\d+(?:\.\d{1,6})?$/.test(rewardText) ? Number(rewardText) : NaN;
  if (!Number.isFinite(rewardAmount) || rewardAmount <= 0) reasons.push("reward_not_positive_verified_usdc");
  const creditsOnly = task?.credits_only === true || (reward == null && task?.reward_credits != null);
  if (creditsOnly) reasons.push("non_cash_reward");
  return {
    source: textField(source, 60),
    title,
    description,
    reward,
    eligible: reasons.length === 0,
    reasons,
    taskId: textField(task?.task_id ?? task?.id, 200),
    assessedAt: new Date().toISOString(),
  };
}

export async function executePrivateDraft(env, task, source = "unknown") {
  const assessment = assessTask(task, source);
  if (!assessment.eligible) return { status: "blocked", assessment, externalActionsTaken: false };
  const team = await executeAgentTeam(env, {
    title: assessment.title,
    description: assessment.description,
  }, assessment.source);
  const qa = qualityCheckDraft(assessment, team.deliverable);
  const submissionReady = team.ready === true && qa.status === "submission_candidate";
  return {
    status: "draft_ready",
    assessment,
    deliverable: team.deliverable,
    qa: { ...qa, independent_review: team.review },
    agentTeam: team.agents,
    revised: team.revised,
    submissionReady,
    externalActionsTaken: false,
    createdAt: new Date().toISOString(),
  };
}

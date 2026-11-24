import { qualityCheckDraft } from "./marketplace_quality.js";
import { executeAgentTeam } from "./marketplace_agent_team.js";

const MAX_TASK_BYTES = 12000;

function textField(value, limit) {
  return typeof value === "string" ? value.trim().slice(0, limit) : "";
}

export function scoreTask(task) {
  const reward = task?.reward ?? task?.reward_usdc ?? task?.reward_amount ?? task?.reward_usd_estimate ?? null;
  const rewardText = typeof reward === "number" ? String(reward) : typeof reward === "string" ? reward.trim() : "";
  const amount = /^\d+(?:\.\d{1,6})?$/.test(rewardText) ? Number(rewardText) : NaN;
  const rewardPoints = Number.isFinite(amount) && amount > 0
    ? Math.round(Math.min(25, 25 * Math.log10(amount + 1) / Math.log10(101)))
    : 0;
  const description = textField(task?.description ?? task?.task_text, MAX_TASK_BYTES);
  const scopePoints = description.length >= 800 ? 25 : description.length >= 400 ? 20 :
    description.length >= 180 ? 15 : description.length >= 80 ? 10 : 5;
  const title = textField(task?.title, 1000);
  const combined = title + " " + description;
  const clarityPoints = (title.length >= 16 ? 5 : 0) +
    (/\b(?:acceptance criteria|deliverable|requirements|provide|include|format|steps|review|test|source|documentation|research|code)\b/i.test(combined) ? 10 : 0) +
    (/\b(?:must|should|exactly|at least|no more than|deadline|submit|verify)\b/i.test(combined) ? 5 : 0);
  const payoutPoints = task?.payout_verified === true ? 20 : task?.eligible === true ? 15 : 0;
  const submissions = Number(task?.submission_count);
  const competitionPoints = Number.isFinite(submissions) && submissions >= 0
    ? submissions === 0 ? 10 : submissions <= 2 ? 9 : submissions <= 5 ? 7 : submissions <= 10 ? 5 : submissions <= 25 ? 3 : submissions <= 50 ? 2 : submissions <= 100 ? 1 : 0
    : 5;
  const breakdown = { reward: rewardPoints, scope: scopePoints, clarity: clarityPoints, payout: payoutPoints, competition: competitionPoints };
  return { total: Math.min(100, Object.values(breakdown).reduce((sum, value) => sum + value, 0)), breakdown };
}

const BLOCK_PATTERNS = [
  /\b(stake|deposit|buy[- ]in|pay to enter|purchase required|claim bond|bounty bond|gas fee|transaction fee)\b/i,
  /\b(wallet connect|connect (?:a|the|your) wallet|sign (?:a|the)? transaction|transaction signing|transfer funds|send crypto|private key|seed phrase)\b/i,
  /\b(?:post|publish|promote|advertise|comment|reply|like|follow)\b.{0,100}\b(?:social|public|account|platform|twitter|x\.com|reddit|linkedin|instagram|facebook)\b|\b(?:social|public|account|platform|twitter|x\.com|reddit|linkedin|instagram|facebook)\b.{0,100}\b(?:post|publish|promote|advertise|comment|reply|like|follow)\b/i,
  /\b(?:cold outreach|cold email|reach out to|send (?:an? )?email to|email (?:the|a|all)\b|dm (?:the|a|all)\b|contact (?:the|a|all)\b|message (?:the|a|all)\b)/i,
  /\b(?:create (?:an? )?account|account creation|register (?:an? )?account|sign[- ]?up|sign[- ]?in|log[- ]?in|login to|credentials|password|access (?:an? )?account|connect (?:an? )?account)\b/i,
  /\b(?:collect|scrape|harvest|extract|compile|gather)\b.{0,100}\b(?:personal data|personal information|pii|email addresses|phone numbers|contact details|private data)\b|\b(?:personal data|personal information|pii|email addresses|phone numbers|contact details|private data)\b.{0,100}\b(?:collect|scrape|harvest|extract|compile|gather)\b/i,
  /\b(?:paid api|paid tool|paid service|subscription|subscribe (?:to|for)|premium (?:plan|tool|service)|purchase credits|buy credits|usage fee|metered api|upfront payment)\b/i,
  /\b(?:install|deploy|configure|modify)\b.{0,100}\b(?:third[- ]party|customer|production|live|remote (?:server|system)|server|system)\b/i,
  /\b(?:pretend (?:you are|to be) (?:a )?human|claim (?:to be|you are) human|impersonate|fake identity|write from personal experience|your personal experience|personally tested|as a customer|as an employee)\b/i,
  /\b(?:medical diagnosis|legal advice|financial advice|investment advice)\b/i,
  /\b(?:malware|credential theft|phishing|exploit|attack|bypass security)\b/i,
];

const UNSUPPORTED_DELIVERABLE_PATTERN = /\b(?:final video|video production|full video|voiceover recording|recorded voice|voice recording|audio recording|podcast production|physical delivery|in[- ]person|on[- ]site|onsite|ship (?:the )?(?:product|item)|live production deployment)\b|\b(?:create|make|produce|edit|record|film|render|deliver)\b.{0,80}\b(?:video|film|movie|podcast|voiceover|voice recording|audio recording)\b|\b(?:video|film|movie|podcast|voiceover|voice recording|audio recording)\b.{0,80}\b(?:production|create|make|produce|edit|record|film|render|deliver)\b|视频|成片|配音|剪辑/i;

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
  if (UNSUPPORTED_DELIVERABLE_PATTERN.test(combined)) {
    reasons.push("unsupported_deliverable");
  }
  for (const pattern of BLOCK_PATTERNS) if (pattern.test(combined)) reasons.push("blocked_risk_pattern:" + pattern.source);
  if (task?.source_policy_verified === false) reasons.push("source_policy_unverified");
  if (task?.eligible === false) reasons.push("marketplace_ineligible");
  if (task?.simulated === true) reasons.push("simulated_task");
  if (task?.stake_required === true) reasons.push("stake_required");
  const submissions = Number(task?.submission_count);
  if (task?.submission_fee_required === true ||
      (String(source).toLowerCase().startsWith("taskmarket") && Number.isInteger(submissions) && submissions >= 5)) {
    reasons.push("submission_fee_required");
  }
  if (String(source).toLowerCase().startsWith("taskmarket")) {
    for (const reason of Array.isArray(task?.taskmarket_qualification_reasons) ? task.taskmarket_qualification_reasons : []) {
      if (typeof reason === "string" && reason.length <= 100 && !reasons.includes(reason)) reasons.push(reason);
    }
    if (task?.taskmarket_freshness_verified === false) reasons.push("taskmarket_snapshot_stale");
    if (task?.taskmarket_escrow_verified !== true) reasons.push("taskmarket_escrow_unverified");
    if (task?.taskmarket_submission_window_open !== true) reasons.push("taskmarket_submission_window_closed");
    if (task?.taskmarket_no_stake_verified === false) reasons.push("stake_required");
  }
  const reward = task?.reward ?? task?.reward_usdc ?? task?.reward_amount ?? null;
  const rewardText = typeof reward === "number" ? String(reward) : typeof reward === "string" ? reward.trim() : "";
  const rewardAmount = /^\d+(?:\.\d{1,6})?$/.test(rewardText) ? Number(rewardText) : NaN;
  if (!Number.isFinite(rewardAmount) || rewardAmount <= 0) reasons.push("reward_not_positive_verified_amount");
  const creditsOnly = task?.credits_only === true || (reward == null && task?.reward_credits != null);
  if (creditsOnly) reasons.push("non_cash_reward");
  const score = scoreTask(task);
  return {
    source: textField(source, 60),
    title,
    description,
    reward,
    eligible: reasons.length === 0,
    reasons,
    score,
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

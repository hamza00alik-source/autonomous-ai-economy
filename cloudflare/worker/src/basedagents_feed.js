const API = "https://api.basedagents.ai";
const MAX_RESPONSE_BYTES = 512_000;
const MAX_TASKS = 100;
const TASK_ID = /^[a-zA-Z0-9_-]{1,120}$/;
const SOCIAL_PATTERN = /\b(tweet|twitter|\bx\b|threads?|comments?|replies|likes|follows|social media|influencer|engagement|promote|promotion|post on (?:your )?(?:account|profile))\b/i;
const HUMAN_PATTERN = /\b(human[- ]only|in[- ]person|physical delivery|record (?:a|your) voice|video production|live production|personal experience|must be human|manual labor)\b/i;
const RISK_PATTERN = /\b(stake|deposit|buy[- ]in|pay to enter|purchase required|wallet connect|connect wallet|sign (?:a|the)? transaction|transfer funds|send crypto|private key|seed phrase|medical diagnosis|legal advice|financial advice|investment advice|malware|credential theft|phishing|exploit|attack|bypass security|cold outreach|spam|pretend you are (?:a )?human)\b/i;
const BASE_NETWORKS = new Set(["eip155:8453", "base", "base mainnet"]);
const CASH_TOKENS = new Set(["USDC"]);

function safeText(value, limit = 12000) {
  return typeof value === "string" ? value.trim().slice(0, limit) : "";
}

function parseUsdc(value) {
  const text = typeof value === "string" ? value.trim() : typeof value === "number" ? String(value) : "";
  if (!/^\d+(?:\.\d{1,6})?$/.test(text)) return null;
  const [whole, fraction = ""] = text.split(".");
  return (BigInt(whole) * 1000000n + BigInt(fraction.padEnd(6, "0"))).toString();
}

function displayUsdc(atomic) {
  if (atomic == null) return null;
  const value = BigInt(atomic);
  return (value / 1000000n).toString() + "." + (value % 1000000n).toString().padStart(6, "0");
}

/**
 * Convert public BasedAgents task data to a conservative AAE discovery record.
 * Discovery is read-only: this never claims, signs, or delivers tasks.
 */
export function normalizeBasedAgentsTask(row, now = Date.now()) {
  if (!row || typeof row !== "object" || Array.isArray(row) || !TASK_ID.test(row.task_id || "")) return null;
  const bounty = row.bounty && typeof row.bounty === "object" ? row.bounty : null;
  const atomic = typeof bounty?.amount_atomic === "string" && /^\d+$/.test(bounty.amount_atomic) ? bounty.amount_atomic : null;
  const amountDisplay = bounty?.amount_display;
  const rewardAtomic = atomic ?? parseUsdc(amountDisplay);
  const token = safeText(bounty?.token, 20).toUpperCase();
  const network = safeText(bounty?.network, 40).toLowerCase();
  const reward = rewardAtomic == null ? null : displayUsdc(rewardAtomic);
  const description = safeText(row.description);
  const title = safeText(row.title, 500);
  const status = safeText(row.status, 30).toLowerCase();
  const capabilities = Array.isArray(row.required_capabilities)
    ? row.required_capabilities.filter(x => typeof x === "string" && x.trim()).slice(0, 20).map(x => x.trim().slice(0, 100))
    : [];
  const expectedOutput = safeText(row.expected_output, 2000);
  const createdAt = safeText(row.created_at, 80);
  const expiresAt = safeText(row.expires_at, 80);
  const creatorKind = safeText(row.creator_kind, 30).toLowerCase();
  const reasons = [];
  if (!title) reasons.push("missing_title");
  if (description.length < 160) reasons.push("task_description_too_short");
  if (status !== "open") reasons.push("not_open");
  if (!bounty || rewardAtomic == null || BigInt(rewardAtomic) < 100000n) reasons.push("missing_or_below_minimum_bounty_0_10_usdc");
  if (row.claimable !== true) reasons.push("bounty_not_verified_claimable");
  if (!CASH_TOKENS.has(token)) reasons.push("not_usdc");
  if (!BASE_NETWORKS.has(network)) reasons.push("not_base_mainnet");
  if (SOCIAL_PATTERN.test(title + "\\n" + description)) reasons.push("social_or_engagement_task");
  if (HUMAN_PATTERN.test(title + "\\n" + description)) reasons.push("human_or_physical_deliverable");
  if (RISK_PATTERN.test(title + "\\n" + description)) reasons.push("prohibited_or_risky_requirement");
  if (row.status === "open" && expiresAt) {
    const expiry = Date.parse(expiresAt);
    if (!Number.isFinite(expiry)) reasons.push("invalid_expiry");
    else if (expiry <= now) reasons.push("expired");
  }
  if (row.claimed_by_agent_id) reasons.push("already_claimed");
  const grossReward = rewardAtomic == null ? 0n : BigInt(rewardAtomic);
  const rewardUsdc = reward == null ? null : reward;
  const eligible = reasons.length === 0;
  const daysRemaining = expiresAt ? (Date.parse(expiresAt) - now) / 86400000 : Infinity;
  const deadlinePenalty = daysRemaining <= 1 ? 10 : daysRemaining <= 3 ? 3 : 0;
  const score = eligible
    ? Number(grossReward > 1000000000n ? 1000000000n : grossReward) / 1000000 +
      (expectedOutput ? 4 : 0) + (capabilities.length ? 2 : 0) - deadlinePenalty
    : 0;
  return {
    source: "basedagents",
    task_id: row.task_id,
    title,
    description,
    status,
    reward_usdc: rewardUsdc,
    reward_atomic: rewardAtomic,
    token,
    network,
    creator_kind: creatorKind || null,
    required_capabilities: capabilities,
    expected_output: expectedOutput || null,
    output_format: safeText(row.output_format, 30) || "text",
    created_at: createdAt || null,
    expires_at: expiresAt || null,
    eligible,
    reasons,
    score,
    snapshot: row,
  };
}

export function rankBasedAgentsTasks(tasks) {
  return [...tasks].filter(task => task?.eligible === true).sort((a, b) => b.score - a.score || (a.task_id || "").localeCompare(b.task_id || ""));
}

async function readJson(response) {
  if (!response.ok) throw new Error("BasedAgents API HTTP " + response.status);
  const contentLength = Number(response.headers?.get?.("content-length") || 0);
  if (contentLength > MAX_RESPONSE_BYTES) throw new Error("BasedAgents response too large");
  const raw = await response.text();
  if (new TextEncoder().encode(raw).byteLength > MAX_RESPONSE_BYTES) throw new Error("BasedAgents response too large");
  return JSON.parse(raw);
}

export async function discoverBasedAgentsTasks(fetchImpl = fetch, now = Date.now()) {
  const url = API + "/v1/tasks?status=open&limit=" + MAX_TASKS;
  const parsedUrl = new URL(url);
  if (parsedUrl.protocol !== "https:" || parsedUrl.hostname !== "api.basedagents.ai") throw new Error("BasedAgents host rejected");
  const response = await fetchImpl(url, {
    method: "GET",
    redirect: "manual",
    headers: { accept: "application/json", "user-agent": "AutonomousAIEconomy/0.1 read-only-discovery" },
    signal: AbortSignal.timeout(12000),
  });
  if (response.status >= 300 && response.status < 400) throw new Error("BasedAgents redirect rejected");
  const data = await readJson(response);
  if (!data || !Array.isArray(data.tasks)) throw new Error("BasedAgents task-list schema changed");
  const normalized = data.tasks.slice(0, MAX_TASKS).map(task => normalizeBasedAgentsTask(task, now)).filter(Boolean);
  const eligible = rankBasedAgentsTasks(normalized);
  return { source: "based_agents", fetched: normalized.length, eligible_count: eligible.length, tasks: normalized, ranked: eligible };
}

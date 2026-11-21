const FEED_URL = "https://agent-bounty-feed.dailydollar.workers.dev/earn-now";
const MAX_FEED_BYTES = 256_000;
const BLOCKED_REQUIREMENTS = new Set(["kyc", "stake", "bond", "purchase", "human_only", "human-only", "first_timers_only", "first-timers-only"]);
const SOCIAL_TASK_PATTERN = /\\b(tweet|twitter|\\bx\\b|kol|influencer|social media|thread|comment|reply|like|follow|engagement|promote|promotion)\\b/i;
const ALLOWED_CURRENCIES = new Set(["USD", "USDC", "USDT", "EUR", "GBP", "USD_EQUIVALENT"]);

function safeSourceUrl(value) {
  if (typeof value !== "string") return null;
  try {
    const url = new URL(value);
    if (url.protocol !== "https:" || url.username || url.password) return null;
    return url.toString();
  } catch {
    return null;
  }
}

export function normalizeBountyFeed(feed, now = Date.now()) {
  if (!feed || typeof feed !== "object" || !Array.isArray(feed.items)) {
    return { items: [], rejected: 1, reason: "invalid_feed_shape" };
  }
  const generatedAt = Date.parse(feed.generated_at || "");
  if (!Number.isFinite(generatedAt) || generatedAt > now + 5 * 60_000 || now - generatedAt > 6 * 60 * 60_000) {
    return { items: [], rejected: feed.items.length, reason: "stale_or_invalid_feed" };
  }
  const items = [];
  let rejected = 0;
  for (const item of feed.items) {
    const reward = Number(item?.est_usd);
    const currency = item?.currency ? String(item.currency).toUpperCase() : "USD_EQUIVALENT";
    const requirements = Array.isArray(item?.requires) ? item.requires.map(x => String(x).toLowerCase()) : [];
    const url = safeSourceUrl(item?.url);
    const deadlineMs = item?.deadline ? Date.parse(item.deadline) : null;
    if (
      (item?.kind != null && item.kind !== "bounty") ||
      typeof item?.id !== "string" || !item.id.trim() ||
      typeof item?.title !== "string" || !item.title.trim() ||
      !url || !Number.isFinite(reward) || reward < 1 ||
      !ALLOWED_CURRENCIES.has(currency) ||
      requirements.some(x => BLOCKED_REQUIREMENTS.has(x)) ||
      SOCIAL_TASK_PATTERN.test([item?.title, item?.one_liner, ...(Array.isArray(item?.how_to_enter) ? item.how_to_enter : [])].filter(Boolean).join(" ")) ||
      (deadlineMs != null && (!Number.isFinite(deadlineMs) || deadlineMs <= now))
    ) {
      rejected++;
      continue;
    }
    items.push({
      bounty_id: item.id.slice(0, 180),
      source: String(item.source || "unknown").slice(0, 80),
      title: item.title.slice(0, 500),
      source_url: url,
      reward_usd: reward,
      currency,
      requirements,
      deadline: item.deadline || null,
      verified_at: item.verified_at || null,
      feed_generated_at: feed.generated_at,
      snapshot: {
        id: item.id,
        title: item.title,
        source: item.source || "unknown",
        url,
        est_usd: reward,
        currency,
        requires: requirements,
        deadline: item.deadline || null,
        verified_at: item.verified_at || null,
        one_liner: typeof item.one_liner === "string" ? item.one_liner.slice(0, 1000) : "",
        how_to_enter: Array.isArray(item.how_to_enter) ? item.how_to_enter.slice(0, 10).map(x => String(x).slice(0, 500)) : [],
      },
    });
  }
  return { items, rejected, reason: null };
}

async function recordRun(env, run) {
  try {
    await env.DB.prepare(
      "INSERT INTO aae_external_bounty_feed_runs (run_id,status,fetched,stored,rejected,feed_generated_at,error,started_at,finished_at) VALUES (?,?,?,?,?,?,?,?,?)"
    ).bind(run.run_id,run.status,run.fetched,run.stored,run.rejected,run.feed_generated_at,run.error,run.started_at,run.finished_at).run();
  } catch {
    // Observability must never hide the original feed result or error.
  }
}

export async function syncExternalBountyFeed(env, fetchImpl = fetch, now = new Date()) {
  const startedAt = now.toISOString();
  const runId = crypto.randomUUID();
  let fetched = 0;
  let stored = 0;
  let rejected = 0;
  let generatedAt = null;
  try {
    const response = await fetchImpl(FEED_URL, {
      method: "GET",
      headers: { accept: "application/json" },
      signal: AbortSignal.timeout(8000),
    });
    if (!response.ok) throw new Error("external bounty feed HTTP " + response.status);
    const text = await response.text();
    if (text.length > MAX_FEED_BYTES) throw new Error("external bounty feed exceeded size limit");
    let feed;
    try { feed = JSON.parse(text); } catch { throw new Error("external bounty feed returned invalid JSON"); }
    generatedAt = feed?.generated_at || null;
    const normalized = normalizeBountyFeed(feed, now.getTime());
    if (normalized.reason) {
      rejected = normalized.rejected;
      const result = { fetched: 0, stored: 0, rejected, reason: normalized.reason };
      await recordRun(env, {run_id:runId,status:"skipped",fetched,stored,rejected,feed_generated_at:generatedAt,error:normalized.reason,started_at:startedAt,finished_at:new Date().toISOString()});
      return result;
    }
    rejected = normalized.rejected;
    for (const item of normalized.items) {
      const result = await env.DB.prepare(
        "INSERT INTO aae_external_bounty_discoveries (bounty_id,source,title,source_url,reward_usd,currency,requirements_json,deadline,verified_at,feed_generated_at,snapshot_json,first_seen_at,last_seen_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(bounty_id) DO UPDATE SET source=excluded.source,title=excluded.title,source_url=excluded.source_url,reward_usd=excluded.reward_usd,currency=excluded.currency,requirements_json=excluded.requirements_json,deadline=excluded.deadline,verified_at=excluded.verified_at,feed_generated_at=excluded.feed_generated_at,snapshot_json=excluded.snapshot_json,last_seen_at=excluded.last_seen_at"
      ).bind(item.bounty_id,item.source,item.title,item.source_url,item.reward_usd,item.currency,JSON.stringify(item.requirements),item.deadline,item.verified_at,item.feed_generated_at,JSON.stringify(item.snapshot),startedAt,startedAt).run();
      if (result.meta?.changes === 1) stored++;
    }
    fetched = normalized.items.length;
    const result = { fetched, stored, rejected, feed_generated_at: generatedAt };
    await recordRun(env, {run_id:runId,status:"success",fetched,stored,rejected,feed_generated_at:generatedAt,error:null,started_at:startedAt,finished_at:new Date().toISOString()});
    return result;
  } catch (error) {
    await recordRun(env, {run_id:runId,status:"failed",fetched,stored,rejected,feed_generated_at:generatedAt,error:String(error?.message||error).slice(0,1000),started_at:startedAt,finished_at:new Date().toISOString()});
    throw error;
  }
}

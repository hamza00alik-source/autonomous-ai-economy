const FEED_URL = "https://jobbi.org/gigs.json?lane=agent&currency=USDC&min_reward=1&limit=100";
const MAX_FEED_BYTES = 1_000_000;
const MAX_MODIFIED_AGE_MS = 7 * 24 * 60 * 60_000;
const TRUSTED_GRADES = new Set(["A", "A-", "B+", "B"]);
const BLOCKED_TEXT = /\b(reddit|twitter|tweet|\bx\.com|social media|thread|comment|reply|like|follow|influencer|kol|promotion|promote|claim bond|\bbond\b|\bstake\b|deposit|purchase|buy|fully fund|fund a child|child bounty|first[_ -]timers?([_ -]only)?|human[_ -]only|macos|safari)\b/i;

function safeHttpsUrl(value) {
  if (typeof value !== "string") return null;
  try {
    const url = new URL(value);
    if (url.protocol !== "https:" || url.username || url.password) return null;
    return url.toString();
  } catch {
    return null;
  }
}

export function normalizeJobbiFeed(feed, now = Date.now()) {
  if (!feed || !Array.isArray(feed.items)) {
    return { items: [], rejected: 1, reason: "invalid_feed_shape" };
  }
  const normalized = [];
  let rejected = 0;
  for (const item of feed.items) {
    const meta = item?._jobbi;
    const reward = Number(meta?.reward?.amount);
    const currency = String(meta?.reward?.currency || "").toUpperCase();
    const rail = String(meta?.reward?.rail || "").toLowerCase();
    const grade = String(meta?.payout_grade || "").toUpperCase();
    const modified = Date.parse(item?.date_modified || "");
    const url = safeHttpsUrl(item?.url);
    const text = [item?.title, item?.content_text, meta?.acceptance, JSON.stringify(meta?.extra || {}), ...(Array.isArray(item?.tags) ? item.tags : [])].filter(Boolean).join(" ");
    const expires = meta?.expires ? Date.parse(meta.expires) : null;
    if (
      typeof item?.id !== "string" || !item.id.trim() ||
      typeof item?.title !== "string" || !item.title.trim() ||
      !url ||
      meta?.lane !== "agent" ||
      meta?.claims_open !== true ||
      meta?.payment_state !== "escrowed" ||
      currency !== "USDC" ||
      rail !== "usdc-base" ||
      !TRUSTED_GRADES.has(grade) ||
      !Number.isFinite(reward) || reward < 1 ||
      !Number.isFinite(modified) || modified > now + 5 * 60_000 || now - modified > MAX_MODIFIED_AGE_MS ||
      (expires != null && (!Number.isFinite(expires) || expires <= now)) ||
      BLOCKED_TEXT.test(text)
    ) {
      rejected++;
      continue;
    }
    const boardSource = String(meta?.source || "unknown").slice(0, 80);
    const requirements = {
      tags: Array.isArray(item.tags) ? item.tags.slice(0, 30).map(x => String(x).slice(0, 80)) : [],
      lane: meta.lane,
      claims_open: meta.claims_open,
      payment_state: meta.payment_state,
      payout_grade: grade,
      payment_rail: rail,
      acceptance_type: meta.acceptance_type || "unknown",
      payout_requires_wallet: true,
    };
    normalized.push({
      gig_id: item.id.slice(0, 180),
      board_source: boardSource,
      title: item.title.slice(0, 500),
      source_url: url,
      reward_usd: reward,
      currency,
      payment_rail: rail,
      payment_state: meta.payment_state,
      payout_grade: grade,
      acceptance_type: String(meta.acceptance_type || "unknown").slice(0, 80),
      requirements,
      deadline: meta.expires || null,
      verified_at: item.date_modified,
      snapshot: {
        id: item.id,
        title: item.title,
        content_text: typeof item.content_text === "string" ? item.content_text.slice(0, 5000) : "",
        tags: requirements.tags,
        date_published: item.date_published || null,
        date_modified: item.date_modified,
        reward: meta.reward,
        acceptance: meta.acceptance || "",
        acceptance_type: meta.acceptance_type || "unknown",
        payment_state: meta.payment_state,
        payout_grade: grade,
        claims_open: meta.claims_open,
        extra: meta.extra || {},
        source_url: url,
      },
    });
  }
  return { items: normalized, rejected, reason: null };
}

async function recordRun(env, run) {
  try {
    await env.DB.prepare(
      "INSERT INTO aae_external_bounty_feed_runs (run_id,source,status,fetched,stored,rejected,feed_generated_at,error,started_at,finished_at) VALUES (?,?,?,?,?,?,?,?,?,?)"
    ).bind(run.run_id,"jobbi",run.status,run.fetched,run.stored,run.rejected,run.feed_generated_at,run.error,run.started_at,run.finished_at).run();
  } catch {
    // Do not mask the scanner result if telemetry storage is unavailable.
  }
}

export async function syncJobbiFeed(env, fetchImpl = fetch, now = new Date()) {
  const startedAt = now.toISOString();
  const runId = crypto.randomUUID();
  let fetched = 0;
  let stored = 0;
  let rejected = 0;
  let feedDate = null;
  try {
    const response = await fetchImpl(FEED_URL, {
      method: "GET",
      headers: { accept: "application/feed+json, application/json" },
      signal: AbortSignal.timeout(8000),
    });
    if (!response.ok) throw new Error("Jobbi feed HTTP " + response.status);
    const text = await response.text();
    if (text.length > MAX_FEED_BYTES) throw new Error("Jobbi feed exceeded size limit");
    let feed;
    try { feed = JSON.parse(text); } catch { throw new Error("Jobbi feed returned invalid JSON"); }
    feedDate = response.headers?.get?.("date") || startedAt;
    const result = normalizeJobbiFeed(feed, now.getTime());
    if (result.reason) {
      rejected = result.rejected;
      await recordRun(env,{run_id:runId,status:"skipped",fetched,stored,rejected,feed_generated_at:feedDate,error:result.reason,started_at:startedAt,finished_at:new Date().toISOString()});
      return { fetched, stored, rejected, reason: result.reason };
    }
    rejected = result.rejected;
    for (const item of result.items) {
      const saved = await env.DB.prepare(
        "INSERT INTO aae_jobbi_discoveries (gig_id,board_source,title,source_url,reward_usd,currency,payment_rail,payment_state,payout_grade,acceptance_type,requirements_json,deadline,verified_at,feed_fetched_at,snapshot_json,first_seen_at,last_seen_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(gig_id) DO UPDATE SET board_source=excluded.board_source,title=excluded.title,source_url=excluded.source_url,reward_usd=excluded.reward_usd,currency=excluded.currency,payment_rail=excluded.payment_rail,payment_state=excluded.payment_state,payout_grade=excluded.payout_grade,acceptance_type=excluded.acceptance_type,requirements_json=excluded.requirements_json,deadline=excluded.deadline,verified_at=excluded.verified_at,feed_fetched_at=excluded.feed_fetched_at,snapshot_json=excluded.snapshot_json,last_seen_at=excluded.last_seen_at"
      ).bind(item.gig_id,item.board_source,item.title,item.source_url,item.reward_usd,item.currency,item.payment_rail,item.payment_state,item.payout_grade,item.acceptance_type,JSON.stringify(item.requirements),item.deadline,item.verified_at,feedDate,JSON.stringify(item.snapshot),startedAt,startedAt).run();
      if (saved.meta?.changes === 1) stored++;
    }
    fetched = result.items.length;
    await recordRun(env,{run_id:runId,status:"success",fetched,stored,rejected,feed_generated_at:feedDate,error:null,started_at:startedAt,finished_at:new Date().toISOString()});
    return { fetched, stored, rejected, feed_fetched_at: feedDate };
  } catch (error) {
    await recordRun(env,{run_id:runId,status:"failed",fetched,stored,rejected,feed_generated_at:feedDate,error:String(error?.message||error).slice(0,1000),started_at:startedAt,finished_at:new Date().toISOString()});
    throw error;
  }
}

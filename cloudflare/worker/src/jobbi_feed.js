const FEED_URL = "https://jobbi.org/gigs.json?lane=agent&limit=1000";
const MAX_FEED_BYTES = 1_000_000;
const MIN_REFRESH_INTERVAL_MS = 60 * 60 * 1000;
const TRUSTED_GRADES = new Set(["A", "A-", "B+", "B"]);
const BLOCKED_TEXT = /\b(reddit|twitter|tweet|\bx\.com|social media|thread|comment|reply|like|follow|influencer|kol|promotion|promote|claim bond|\bbond\b|\bstake\b|deposit|purchase|buy|fully fund|fund a child|child bounty|first[_ -]timers?([_ -]only)?|human[_ -]only|macos|safari|cold outreach|send (?:an )?email|dm (?:the|a)|contact (?:the|a)|install (?:this|the|a)|deploy to production|production system|customer data|personal data|pii|kyc|sign (?:a )?contract|legal advice|financial advice|investment advice|paid api|subscription required|api key required)\b/i;

// Explicit payout rails only. Unknown rails are never silently treated as cash.
const PAYOUT_RAILS = {
  "usdc-base": { asset: "USDC", network: "Base", kind: "stablecoin", priority: 0, region: "wallet_required" },
  "usdc-arbitrum": { asset: "USDC", network: "Arbitrum", kind: "stablecoin", priority: 1, region: "wallet_required" },
  "usdc-optimism": { asset: "USDC", network: "Optimism", kind: "stablecoin", priority: 1, region: "wallet_required" },
  "usdc-polygon": { asset: "USDC", network: "Polygon", kind: "stablecoin", priority: 1, region: "wallet_required" },
  "usdc-ethereum": { asset: "USDC", network: "Ethereum", kind: "stablecoin", priority: 1, region: "wallet_required" },
  "usdc-avalanche": { asset: "USDC", network: "Avalanche", kind: "stablecoin", priority: 1, region: "wallet_required" },
  "usdt-tron": { asset: "USDT", network: "Tron", kind: "stablecoin", priority: 1, region: "wallet_required" },
  "usdt-ethereum": { asset: "USDT", network: "Ethereum", kind: "stablecoin", priority: 1, region: "wallet_required" },
  "usdt-polygon": { asset: "USDT", network: "Polygon", kind: "stablecoin", priority: 1, region: "wallet_required" },
  "usdt-arbitrum": { asset: "USDT", network: "Arbitrum", kind: "stablecoin", priority: 1, region: "wallet_required" },
  "eth-mainnet": { asset: "ETH", network: "Ethereum", kind: "crypto", priority: 2, region: "wallet_required" },
  "btc-mainnet": { asset: "BTC", network: "Bitcoin", kind: "crypto", priority: 2, region: "wallet_required" },
  "sol-solana": { asset: "SOL", network: "Solana", kind: "crypto", priority: 2, region: "wallet_required" },
  "payoneer": { assets: ["USD", "EUR", "GBP"], network: "Payoneer", kind: "digital_payout", priority: 3, region: "supported_in_pakistan" },
  "wise": { assets: ["USD", "EUR", "GBP"], network: "Wise", kind: "digital_payout", priority: 4, region: "account_confirmation_required" },
  "skrill": { assets: ["USD", "EUR", "GBP"], network: "Skrill", kind: "digital_payout", priority: 5, region: "account_confirmation_required" },
  "neteller": { assets: ["USD", "EUR", "GBP"], network: "Neteller", kind: "digital_payout", priority: 5, region: "account_confirmation_required" },
};

function safeHttpsUrl(value) {
  if (typeof value !== "string") return null;
  try {
    const url = new URL(value);
    if (url.protocol !== "https:" || url.username || url.password) return null;
    return url.toString();
  } catch { return null; }
}

function classifyPayout(reward, railValue, extra = {}) {
  const currency = String(reward?.currency || "").trim().toUpperCase();
  const rail = String(railValue || "").trim().toLowerCase();
  const spec = PAYOUT_RAILS[rail];
  if (spec) {
    const matches = Array.isArray(spec.assets) ? spec.assets.includes(currency) : spec.asset === currency;
    return matches ? { rail, currency, ...spec } : null;
  }
  // Accept other crypto only when both asset and chain are explicit and a USD estimate is supplied.
  const networks = {
    base: "Base", ethereum: "Ethereum", polygon: "Polygon", arbitrum: "Arbitrum",
    optimism: "Optimism", avalanche: "Avalanche", solana: "Solana", bitcoin: "Bitcoin",
    tron: "Tron", bsc: "BNB Smart Chain", ton: "TON", near: "NEAR", sui: "Sui",
    aptos: "Aptos", stellar: "Stellar", xrp: "XRP Ledger",
  };
  const match = rail.match(/^([a-z0-9]+)-([a-z0-9]+)$/);
  const network = match && networks[match[2]];
  const usdEstimate = Number(reward?.usd_estimate ?? extra?.reward_usd_estimate);
  if (match && match[1].toUpperCase() === currency && network && currency !== "USDC" && currency !== "USDT" &&
      Number.isFinite(usdEstimate) && usdEstimate > 0) {
    return { rail, currency, network, kind: "crypto", priority: 2, region: "wallet_required" };
  }
  return null;
}

function acceptanceText(item, meta) {
  return [meta?.acceptance, meta?.acceptance_type, item?.content_text]
    .filter(x => typeof x === "string").join(" ").trim();
}

export function normalizeJobbiFeed(feed, now = Date.now()) {
  if (!feed || !Array.isArray(feed.items)) return { items: [], rejected: 1, reason: "invalid_feed_shape" };
  const normalized = [];
  let rejected = 0;
  for (const item of feed.items) {
    const meta = item?._jobbi;
    const reward = Number(meta?.reward?.amount);
    const payout = classifyPayout(meta?.reward, meta?.reward?.rail, meta?.extra);
    const grade = String(meta?.payout_grade || "").toUpperCase();
    const modified = Date.parse(item?.date_modified || "");
    const url = safeHttpsUrl(item?.url);
    const criteria = acceptanceText(item, meta);
    const expires = meta?.expires ? Date.parse(meta.expires) : NaN;
    const text = [item?.title, item?.content_text, meta?.acceptance, JSON.stringify(meta?.extra || {}), ...(Array.isArray(item?.tags) ? item.tags : [])].filter(Boolean).join(" ");
    const reasons = [];
    if (!payout) reasons.push("payout_rail_or_asset_not_explicitly_supported");
    if (typeof item?.id !== "string" || !item.id.trim()) reasons.push("missing_task_id");
    if (typeof item?.title !== "string" || !item.title.trim()) reasons.push("missing_title");
    if (!url) reasons.push("invalid_source_url");
    if (meta?.lane !== "agent") reasons.push("not_agent_lane");
    if (meta?.claims_open !== true) reasons.push("claims_not_open");
    if (meta?.payment_state !== "escrowed") reasons.push("reward_not_reported_escrowed");
    if (!TRUSTED_GRADES.has(grade)) reasons.push("payout_confidence_below_B");
    if (!Number.isFinite(reward) || reward <= 0) reasons.push("invalid_reward_amount");
    if (!Number.isFinite(modified) || modified > now + 5 * 60_000 || now - modified > 7 * 24 * 60 * 60_000) reasons.push("stale_or_invalid_listing");
    if (!Number.isFinite(expires) || expires <= now) reasons.push("deadline_missing_or_expired");
    if (criteria.length < 45 || !meta?.acceptance) reasons.push("acceptance_criteria_missing");
    if (BLOCKED_TEXT.test(text)) reasons.push("prohibited_or_costly_requirement");
    if (reasons.length) { rejected++; continue; }

    const usdEstimate = payout.kind === "stablecoin" && ["USDC", "USDT"].includes(payout.currency)
      ? reward
      : Number.isFinite(Number(meta?.reward?.usd_estimate)) ? Number(meta.reward.usd_estimate)
      : Number.isFinite(Number(meta?.extra?.reward_usd_estimate)) ? Number(meta.extra.reward_usd_estimate)
      : null;
    const requirements = {
      lane: meta.lane,
      claims_open: meta.claims_open,
      payment_state: meta.payment_state,
      payout_grade: grade,
      payout_rail: payout.rail,
      payout_kind: payout.kind,
      payout_asset: payout.currency,
      payout_network: payout.network,
      payout_region_status: payout.region,
      payout_account_required: payout.kind !== "stablecoin" && payout.kind !== "crypto",
      payout_account_access: "owner-provided authorization only; never request passwords, seed phrases, or private keys in chat",
      acceptance_type: meta.acceptance_type || "unknown",
      acceptance_criteria: String(meta.acceptance).slice(0, 5000),
      source_live_verification: "jobbi_index_only; recheck original board before any owner-approved work",
      no_claim_or_submission: true,
    };
    normalized.push({
      gig_id: item.id.slice(0, 180),
      board_source: String(meta?.source || "unknown").slice(0, 80),
      title: item.title.slice(0, 500),
      source_url: url,
      reward_usd: usdEstimate ?? reward,
      reward_amount: reward,
      reward_usd_estimate: usdEstimate,
      currency: payout.currency,
      payment_rail: payout.rail,
      payment_state: meta.payment_state,
      payout_grade: grade,
      payout_priority: payout.priority,
      payout_network: payout.network,
      payout_region_status: payout.region,
      acceptance_type: String(meta.acceptance_type || "unknown").slice(0, 80),
      requirements,
      deadline: meta.expires,
      verified_at: item.date_modified,
      snapshot: {
        id: item.id, title: item.title,
        content_text: typeof item.content_text === "string" ? item.content_text.slice(0, 5000) : "",
        tags: Array.isArray(item.tags) ? item.tags.slice(0, 30).map(x => String(x).slice(0, 80)) : [],
        date_published: item.date_published || null,
        date_modified: item.date_modified,
        reward: meta.reward,
        acceptance: meta.acceptance,
        acceptance_type: meta.acceptance_type || "unknown",
        payment_state: meta.payment_state,
        payout_grade: grade,
        claims_open: meta.claims_open,
        source: meta.source || "unknown",
        source_url: url,
        payout: requirements,
      },
    });
  }
  normalized.sort((a,b) => a.payout_priority - b.payout_priority ||
    (b.reward_usd_estimate ?? -1) - (a.reward_usd_estimate ?? -1) ||
    Date.parse(a.deadline) - Date.parse(b.deadline));
  return { items: normalized, rejected, reason: null };
}

async function recordRun(env, run) {
  try {
    await env.DB.prepare(
      "INSERT INTO aae_external_bounty_feed_runs (run_id,source,status,fetched,stored,rejected,feed_generated_at,error,started_at,finished_at) VALUES (?,?,?,?,?,?,?,?,?,?)"
    ).bind(run.run_id,"jobbi",run.status,run.fetched,run.stored,run.rejected,run.feed_generated_at,run.error,run.started_at,run.finished_at).run();
  } catch { /* telemetry must not mask discovery */ }
}

export async function syncJobbiFeed(env, fetchImpl = fetch, now = new Date()) {
  const startedAt = now.toISOString();
  const runId = crypto.randomUUID();
  let fetched = 0, stored = 0, rejected = 0, feedDate = null;
  try {
    const previous = await env.DB.prepare(
      "SELECT finished_at FROM aae_external_bounty_feed_runs WHERE source='jobbi' AND status='success' ORDER BY finished_at DESC LIMIT 1"
    ).first();
    const previousAt = Date.parse(previous?.finished_at || "");
    if (Number.isFinite(previousAt) && now.getTime() - previousAt < MIN_REFRESH_INTERVAL_MS) {
      return { fetched: 0, stored: 0, rejected: 0, skipped: "hourly_rate_limit", next_poll_at: new Date(previousAt + MIN_REFRESH_INTERVAL_MS).toISOString() };
    }
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
    feedDate = response.headers?.get?.("last-modified") || response.headers?.get?.("date") || startedAt;
    const result = normalizeJobbiFeed(feed, now.getTime());
    if (result.reason) {
      rejected = result.rejected;
      await recordRun(env,{run_id:runId,status:"skipped",fetched,stored,rejected,feed_generated_at:feedDate,error:result.reason,started_at:startedAt,finished_at:new Date().toISOString()});
      return { fetched, stored, rejected, reason: result.reason };
    }
    rejected = result.rejected;
    for (const item of result.items) {
      const saved = await env.DB.prepare(
        "INSERT INTO aae_jobbi_discoveries (gig_id,board_source,title,source_url,reward_usd,currency,payment_rail,payment_state,payout_grade,acceptance_type,requirements_json,deadline,verified_at,feed_fetched_at,snapshot_json,first_seen_at,last_seen_at,reward_amount,reward_usd_estimate,payout_network,payout_region_status,payout_priority) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(gig_id) DO UPDATE SET board_source=excluded.board_source,title=excluded.title,source_url=excluded.source_url,reward_usd=excluded.reward_usd,currency=excluded.currency,payment_rail=excluded.payment_rail,payment_state=excluded.payment_state,payout_grade=excluded.payout_grade,acceptance_type=excluded.acceptance_type,requirements_json=excluded.requirements_json,deadline=excluded.deadline,verified_at=excluded.verified_at,feed_fetched_at=excluded.feed_fetched_at,snapshot_json=excluded.snapshot_json,last_seen_at=excluded.last_seen_at,reward_amount=excluded.reward_amount,reward_usd_estimate=excluded.reward_usd_estimate,payout_network=excluded.payout_network,payout_region_status=excluded.payout_region_status,payout_priority=excluded.payout_priority"
      ).bind(item.gig_id,item.board_source,item.title,item.source_url,item.reward_usd,item.currency,item.payment_rail,item.payment_state,item.payout_grade,item.acceptance_type,JSON.stringify(item.requirements),item.deadline,item.verified_at,feedDate,JSON.stringify(item.snapshot),startedAt,startedAt,item.reward_amount,item.reward_usd_estimate,item.payout_network,item.payout_region_status,item.payout_priority).run();
      if (saved.meta?.changes === 1) stored++;
      fetched++;
    }
    await recordRun(env,{run_id:runId,status:"success",fetched,stored,rejected,feed_generated_at:feedDate,error:null,started_at:startedAt,finished_at:new Date().toISOString()});
    return { fetched, stored, rejected, feed_fetched_at: feedDate };
  } catch (error) {
    await recordRun(env,{run_id:runId,status:"failed",fetched,stored,rejected,feed_generated_at:feedDate,error:String(error?.message||error).slice(0,1000),started_at:startedAt,finished_at:new Date().toISOString()});
    throw error;
  }
}

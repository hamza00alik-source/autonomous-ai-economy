const API_URL = "https://elgora.ai/api/bounties?status=open&min_amount=1000000";
const BASE_URL = "https://elgora.ai";
const BASE_CHAIN_ID = 8453;
const USDC_BASE = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913";
const DEFAULT_SUBMISSION_CAP = 10;
const MAX_RESPONSE_BYTES = 512_000;

export function normalizeElgoraList(payload, now = Date.now()) {
  if (!payload || Number(payload.chain_id) !== BASE_CHAIN_ID || typeof payload.hub_address !== "string" || !Array.isArray(payload.bounties)) {
    return { items: [], rejected: 1, reason: "invalid_elgora_list_shape" };
  }
  const items = [];
  let rejected = 0;
  for (const bounty of payload.bounties) {
    const amount = Number(bounty?.escrow?.amount);
    const token = String(bounty?.escrow?.token_address || "").toLowerCase();
    const deadline = Number(bounty?.submission_deadline);
    const submissions = Number(bounty?.submission_count);
    const id = String(bounty?.bounty_id || "");
    if (
      bounty?.status !== "open" ||
      !/^\d+$/.test(id) ||
      token !== USDC_BASE ||
      !Number.isSafeInteger(amount) || amount < 1_000_000 ||
      !Number.isFinite(deadline) || deadline * 1000 <= now ||
      !Number.isInteger(submissions) || submissions < 0 || submissions >= DEFAULT_SUBMISSION_CAP
    ) {
      rejected++;
      continue;
    }
    const reward = amount / 1_000_000;
    const url = BASE_URL + "/bounties/" + id;
    items.push({
      bounty_id: "elgora:" + id,
      title: "Elgora bounty #" + id,
      source_url: url,
      reward_usd: reward,
      currency: "USDC",
      requirements: {
        chain_id: BASE_CHAIN_ID,
        hub_address: payload.hub_address,
        token_address: USDC_BASE,
        escrow_amount_base_units: String(amount),
        submission_count: submissions,
        assumed_submission_cap: DEFAULT_SUBMISSION_CAP,
        remaining_slots_estimate: DEFAULT_SUBMISSION_CAP - submissions,
        verify_guard_override_before_submission: true,
        wallet_required: true,
        native_base_gas_required: true,
        submission_requires_owner_approval: true,
      },
      deadline: new Date(deadline * 1000).toISOString(),
      verified_at: new Date(now).toISOString(),
      snapshot: { ...bounty, source_api: API_URL, submission_capacity_is_default_assumption: true },
    });
  }
  return { items, rejected, reason: null };
}

async function recordRun(env, run) {
  try {
    await env.DB.prepare(
      "INSERT INTO aae_external_bounty_feed_runs (run_id,source,status,fetched,stored,rejected,feed_generated_at,error,started_at,finished_at) VALUES (?,?,?,?,?,?,?,?,?,?)"
    ).bind(run.run_id,"elgora",run.status,run.fetched,run.stored,run.rejected,run.feed_generated_at,run.error,run.started_at,run.finished_at).run();
  } catch {
    // Keep the discovery result independent from telemetry availability.
  }
}

export async function syncElgoraList(env, fetchImpl = fetch, now = new Date()) {
  const startedAt = now.toISOString();
  const runId = crypto.randomUUID();
  let fetched = 0;
  let stored = 0;
  let rejected = 0;
  try {
    const response = await fetchImpl(API_URL, {
      method: "GET",
      headers: { accept: "application/json" },
      signal: AbortSignal.timeout(8000),
    });
    if (!response.ok) throw new Error("Elgora list HTTP " + response.status);
    const text = await response.text();
    if (text.length > MAX_RESPONSE_BYTES) throw new Error("Elgora list exceeded size limit");
    let payload;
    try { payload = JSON.parse(text); } catch { throw new Error("Elgora list returned invalid JSON"); }
    const normalized = normalizeElgoraList(payload, now.getTime());
    if (normalized.reason) {
      rejected = normalized.rejected;
      await recordRun(env,{run_id:runId,status:"skipped",fetched,stored,rejected,feed_generated_at:startedAt,error:normalized.reason,started_at:startedAt,finished_at:new Date().toISOString()});
      return { fetched, stored, rejected, reason: normalized.reason };
    }
    rejected = normalized.rejected;
    for (const item of normalized.items) {
      const saved = await env.DB.prepare(
        "INSERT INTO aae_external_bounty_discoveries (bounty_id,source,title,source_url,reward_usd,currency,requirements_json,deadline,verified_at,feed_generated_at,snapshot_json,first_seen_at,last_seen_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(bounty_id) DO UPDATE SET title=excluded.title,source_url=excluded.source_url,reward_usd=excluded.reward_usd,currency=excluded.currency,requirements_json=excluded.requirements_json,deadline=excluded.deadline,verified_at=excluded.verified_at,feed_generated_at=excluded.feed_generated_at,snapshot_json=excluded.snapshot_json,last_seen_at=excluded.last_seen_at"
      ).bind(item.bounty_id,"elgora",item.title,item.source_url,item.reward_usd,item.currency,JSON.stringify(item.requirements),item.deadline,item.verified_at,startedAt,JSON.stringify(item.snapshot),startedAt,startedAt).run();
      if (saved.meta?.changes === 1) stored++;
      fetched++;
    }
    await recordRun(env,{run_id:runId,status:"success",fetched,stored,rejected,feed_generated_at:startedAt,error:null,started_at:startedAt,finished_at:new Date().toISOString()});
    return { fetched, stored, rejected, feed_fetched_at: startedAt };
  } catch (error) {
    await recordRun(env,{run_id:runId,status:"failed",fetched,stored,rejected,feed_generated_at:startedAt,error:String(error?.message||error).slice(0,1000),started_at:startedAt,finished_at:new Date().toISOString()});
    throw error;
  }
}

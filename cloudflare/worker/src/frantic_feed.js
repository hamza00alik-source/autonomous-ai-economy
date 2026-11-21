const BOARD_URL = "https://gofrantic.com/v1/board";
const BASE_URL = "https://gofrantic.com";
const MAX_BOARD_BYTES = 512_000;
const MAX_BOUNTY_BYTES = 128_000;
const MAX_DETAILS_PER_RUN = 10;
const BLOCKED_TEXT = /\b(reddit|twitter|tweet|\bx\.com|social media|thread|comment|reply|like|follow|influencer|kol|promotion|promote|external citation|citation|outreach|email the author|guest piece|blog post|linkedin|substack|medium|quora|fund a bounty|funding|deposit|purchase|\bbond\b|\bstake\b|upfront payment|first five funders)\b/i;
const TECHNICAL_WORK = /\b(pull request|github|repository|code|data|api|bug|test|docs|documentation|research|integration|yaml|schema)\b/i;

function safeApiPath(value) {
  return typeof value === "string" && /^\\/v1\\/bounties\\/(?:\\d+|p-[a-f0-9]+)$/.test(value) ? value : null;
}

async function readJson(response, maxBytes, label) {
  if (!response.ok) throw new Error(label + " HTTP " + response.status);
  const text = await response.text();
  if (text.length > maxBytes) throw new Error(label + " exceeded size limit");
  try { return JSON.parse(text); } catch { throw new Error(label + " returned invalid JSON"); }
}

export function normalizeFranticBoard(board) {
  const entries = board?.board?.open_bounties;
  if (!Array.isArray(entries)) return { items: [], rejected: 1, reason: "invalid_board_shape" };
  const items = [];
  let rejected = 0;
  for (const entry of entries) {
    const price = Number(entry?.price_usd);
    const slots = Number(entry?.claim_slots?.available);
    const apiPath = safeApiPath(entry?.api_url);
    const content = [entry?.title, entry?.note].filter(Boolean).join(" ");
    if (
      !Number.isFinite(Number(entry?.number)) ||
      !entry?.funded ||
      entry?.work_status !== "open" ||
      !Number.isFinite(price) || price < 1 || price > 10 ||
      !Number.isFinite(slots) || slots < 1 ||
      entry?.actions?.claim?.available !== true ||
      !apiPath ||
      !TECHNICAL_WORK.test(content) ||
      BLOCKED_TEXT.test(content)
    ) {
      rejected++;
      continue;
    }
    items.push({
      number: Number(entry.number),
      title: String(entry.title || "").slice(0, 500),
      price_usd: price,
      api_path: apiPath,
      board_snapshot: entry,
    });
  }
  return { items: items.slice(0, MAX_DETAILS_PER_RUN), rejected: rejected + Math.max(0, items.length - MAX_DETAILS_PER_RUN), reason: null };
}

async function recordRun(env, run) {
  try {
    await env.DB.prepare(
      "INSERT INTO aae_external_bounty_feed_runs (run_id,source,status,fetched,stored,rejected,feed_generated_at,error,started_at,finished_at) VALUES (?,?,?,?,?,?,?,?,?,?)"
    ).bind(run.run_id,"frantic",run.status,run.fetched,run.stored,run.rejected,run.feed_generated_at,run.error,run.started_at,run.finished_at).run();
  } catch {
    // Telemetry must not mask the discovery result.
  }
}

export async function syncFranticFeed(env, fetchImpl = fetch, now = new Date()) {
  const startedAt = now.toISOString();
  const runId = crypto.randomUUID();
  let fetched = 0;
  let stored = 0;
  let rejected = 0;
  try {
    const boardResponse = await fetchImpl(BOARD_URL, {
      method: "GET",
      headers: { accept: "application/json" },
      signal: AbortSignal.timeout(8000),
    });
    const board = await readJson(boardResponse, MAX_BOARD_BYTES, "Frantic board");
    const normalized = normalizeFranticBoard(board);
    if (normalized.reason) {
      rejected = normalized.rejected;
      await recordRun(env,{run_id:runId,status:"skipped",fetched,stored,rejected,feed_generated_at:startedAt,error:normalized.reason,started_at:startedAt,finished_at:new Date().toISOString()});
      return { fetched, stored, rejected, reason: normalized.reason };
    }
    rejected = normalized.rejected;
    for (const item of normalized.items) {
      let detail;
      try {
        const response = await fetchImpl(BASE_URL + item.api_path, {
          method: "GET",
          headers: { accept: "application/json" },
          signal: AbortSignal.timeout(8000),
        });
        detail = await readJson(response, MAX_BOUNTY_BYTES, "Frantic bounty " + item.number);
      } catch {
        rejected++;
        continue;
      }
      const bounty = detail?.bounty;
      const available = Number(bounty?.claim_progress?.available);
      const funded = bounty?.funded === true;
      const livePrice = Number(bounty?.price_usd);
      const fullText = [bounty?.title, bounty?.description, bounty?.criteria?.description].filter(Boolean).join(" ");
      if (
        !funded ||
        !Number.isFinite(available) || available < 1 ||
        !Number.isFinite(livePrice) || livePrice < 1 || livePrice > 10 ||
        BLOCKED_TEXT.test(fullText) ||
        !TECHNICAL_WORK.test(fullText)
      ) {
        rejected++;
        continue;
      }
      const timestamp = now.toISOString();
      const requirements = {
        payout_currency: "USDC",
        payout_network: "Base",
        payout_rail: "x402",
        payout_wallet_required: true,
        verified_contact_required: true,
        standard_paid_eligibility_required: false,
        claim_slots_available: available,
        claim_requires: Array.isArray(bounty?.criteria?.verification?.requires) ? bounty.criteria.verification.requires : [],
        external_submission: "GitHub pull request or other task-defined artifact; review before claim",
      };
      const snapshot = {
        board: item.board_snapshot,
        bounty: {
          number: bounty.number,
          title: bounty.title,
          description: bounty.description,
          price_usd: livePrice,
          funded: bounty.funded,
          work_status: bounty.work_status,
          claim_progress: bounty.claim_progress,
          criteria: bounty.criteria,
          required_artifacts: bounty.required_artifacts,
          posted_at: bounty.posted_at,
        },
      };
      const saved = await env.DB.prepare(
        "INSERT INTO aae_external_bounty_discoveries (bounty_id,source,title,source_url,reward_usd,currency,requirements_json,deadline,verified_at,feed_generated_at,snapshot_json,first_seen_at,last_seen_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(bounty_id) DO UPDATE SET title=excluded.title,source_url=excluded.source_url,reward_usd=excluded.reward_usd,currency=excluded.currency,requirements_json=excluded.requirements_json,deadline=excluded.deadline,verified_at=excluded.verified_at,feed_generated_at=excluded.feed_generated_at,snapshot_json=excluded.snapshot_json,last_seen_at=excluded.last_seen_at"
      ).bind("frantic:"+item.number,"frantic",bounty.title,BASE_URL+"/bounties/"+item.number,livePrice,"USDC",JSON.stringify(requirements),bounty.deadline||null,timestamp,timestamp,JSON.stringify(snapshot),timestamp,timestamp).run();
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

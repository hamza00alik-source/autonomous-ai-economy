const API = "https://api.taskmarket.dev";
const RPCS = ["https://mainnet.base.org", "https://base-rpc.publicnode.com"];
const CHAIN_ID = 8453;
const DIAMOND = "0xddc6cc3e4d11c1f3527b867c7dad4ed9869c33f7";
const TASK_CREATED_TOPIC = "0xe0dc4072f8420c56e984e9c6eec7bad2e5616825f0d1ca581bd96ff3e8eec948";
const ESCROW_FUNDED_TOPIC = "0x201d660f753914e19eddd41fa59c8765f90e47e94e92d03ea727a9280636ed79";
const BOUNTY_MODE_TOPIC = "0xa81913a5" + "0".repeat(56);
const MAX_BYTES = 3_000_000;
const MAX_TASKS_PER_POLL = 20;
const TASK_ID = /^0x[a-f0-9]{64}$/i;
const TX_HASH = /^0x[a-f0-9]{64}$/i;

function bounded(value, max = 500) {
  return typeof value === "string" ? value.trim().slice(0, max) : "";
}
function usdc(baseUnits) {
  try {
    const n = BigInt(String(baseUnits));
    if (n < 0n) return null;
    return (n / 1000000n).toString() + "." + (n % 1000000n).toString().padStart(6, "0");
  } catch { return null; }
}
async function readJson(response, label) {
  if (!response.ok) throw new Error(label + " HTTP " + response.status);
  const length = Number(response.headers.get("content-length") || 0);
  if (length > MAX_BYTES) throw new Error(label + " response too large");
  const raw = await response.text();
  if (new TextEncoder().encode(raw).length > MAX_BYTES) throw new Error(label + " response too large");
  return JSON.parse(raw);
}
async function fetchJson(url, init = {}, fetchImpl = fetch) {
  const parsed = new URL(url);
  if (parsed.protocol !== "https:" || !["api.taskmarket.dev", "mainnet.base.org", "base-rpc.publicnode.com"].includes(parsed.hostname)) {
    throw new Error("external host rejected");
  }
  const response = await fetchImpl(url, {
    ...init, redirect: "manual",
    headers: { accept: "application/json", "user-agent": "AutonomousAIEconomy/0.1 read-only-discovery", ...(init.headers || {}) },
    signal: AbortSignal.timeout(12000),
  });
  if (response.status >= 300 && response.status < 400) throw new Error("redirect rejected");
  return readJson(response, parsed.hostname);
}

async function fetchRpcJson(init, fetchImpl = fetch) {
  const failures = [];
  for (const endpoint of RPCS) {
    try { return await fetchJson(endpoint, init, fetchImpl); }
    catch (error) { failures.push(endpoint + ": " + String(error?.message || error).slice(0, 120)); }
  }
  throw new Error("all Base RPC providers failed: " + failures.join("; "));
}
export function normalizeTaskmarketTask(row, now = Date.now()) {
  if (!row || typeof row !== "object" || Array.isArray(row) || !TASK_ID.test(row.id || "")) return null;
  const reward = String(row.reward ?? "");
  const description = bounded(row.description, 20000);
  const escrow = row.escrow && typeof row.escrow === "object" ? row.escrow : null;
  const platformFeeBps = Number.isInteger(Number(row.platformFeeBps)) ? Number(row.platformFeeBps) : 0;
  const rewardIsInteger = /^[0-9]+$/.test(reward);
  const gross = rewardIsInteger ? BigInt(reward) : 0n;
  const fee = platformFeeBps >= 0 && platformFeeBps <= 10000 ? gross * BigInt(platformFeeBps) / 10000n : gross;
  const netReward = (gross - fee).toString();
  const count = Number.isInteger(Number(row.submissionCount)) ? Number(row.submissionCount) : 999999;
  const stakeBps = Number.isInteger(Number(row.stakeBps)) ? Number(row.stakeBps) : 999999;
  const chainId = Number(row.chainId || 0);
  const expiry = row.expiryTime ? bounded(row.expiryTime, 80) : null;
  const reasons = [];
  if (chainId !== CHAIN_ID) reasons.push("not_base_mainnet");
  if (row.status !== "open") reasons.push("not_open");
  if (row.mode !== "bounty") reasons.push("not_bounty");
  if (!/^0x[0-9a-f]{40}$/i.test(String(row.requester || ""))) reasons.push("requester_address_missing");
  if (!/^[0-9]+$/.test(reward) || BigInt(reward || "0") < 1000000n) reasons.push("gross_reward_below_1_usdc");
  if (!/^[0-9]+$/.test(netReward) || BigInt(netReward || "0") < 1000000n) reasons.push("net_reward_below_1_usdc");
  if (row.stakeRequired === true || stakeBps > 0) reasons.push("deposit_or_stake_required");
  if (!expiry) reasons.push("expiry_missing");
  // Taskmarket's first five bounty submissions are free; the next submission incurs a paid action.
  if (count >= 50) reasons.push("submission_fee_threshold_reached");
  if (!description || description.length < 120) reasons.push("insufficient_task_details");
  if (/split equally|share the full pool|first\s+\d+\s+(?:qualifying\s+)?agents|one award per|up to\s+\d+\s+(?:accepted|qualifying)|split.{0,80}\b\d+\s*%|split.{0,80}\b\d+\s*\/\s*\d+/i.test(description)) reasons.push("split_reward_pool");
  if (/public (?:post|reply|conversation)|paid promotion|promotional post|social media|post on your own account|\b(?:threads?|comments?)\b.{0,160}\b(?:X|Twitter|Reddit|Instagram|TikTok|Facebook|LinkedIn)\b/i.test(description)) reasons.push("public_promotion_required");
  if (/off-platform|paid off-platform|listing deposit|not a per-worker payout|BEP-?20|worker address.{0,40}sign/i.test(description)) reasons.push("off_platform_or_wallet_risk");
  if (expiry) {
    const parsed = Date.parse(expiry);
    if (!Number.isFinite(parsed)) reasons.push("invalid_expiry");
    else if (parsed <= now) reasons.push("expired");
  }
  const tx = typeof row.escrowTxHash === "string" && TX_HASH.test(row.escrowTxHash) ? row.escrowTxHash : null;
  if (!tx) reasons.push("escrow_transaction_missing");
  const titleLines = description.split("\n").map(line => line.trim()).filter(Boolean);
  const titleLine = titleLines.find(line => !/^#{1,6}\s*(?:title|任务标题)\s*$/i.test(line));
  return {
    task_id: row.id.toLowerCase(),
    title: bounded(titleLine?.replace(/^#{1,6}\s*/, "") || "Untitled task", 300),
    description,
    chain_id: chainId,
    mode: bounded(row.mode, 30),
    board_state: bounded(row.status, 30),
    reward_base_units: reward,
    reward_usdc: usdc(reward),
    net_reward_base_units: netReward,
    net_reward_usdc: usdc(netReward),
    escrow_tx_hash: tx,
    escrow_tracked: escrow?.tracked === true ? 1 : 0,
    escrow_booked_base_units: escrow?.booked === undefined ? null : String(escrow.booked),
    submission_count: count,
    stake_required: row.stakeRequired === true ? 1 : 0,
    stake_bps: stakeBps,
    platform_fee_bps: Number(row.platformFeeBps || 0),
    submission_window_open: row.status === "open" && !!expiry && Date.parse(expiry) > now ? 1 : 0,
    expiry_time: expiry,
    requester: bounded(row.requester, 100),
    tags_json: JSON.stringify(Array.isArray(row.tags) ? row.tags.filter(x => typeof x === "string").slice(0, 20) : []),
    qualification_reasons: reasons,
    eligible: reasons.length === 0 ? 1 : 0,
  };
}
export async function verifyTaskmarketEscrow(task, fetchImpl = fetch) {
  if (!task.escrow_tx_hash) return { verified: false, status: "missing_escrow_transaction" };
  const receiptPayload = await fetchRpcJson({
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "eth_getTransactionReceipt", params: [task.escrow_tx_hash] }),
  }, fetchImpl);
  const receipt = receiptPayload?.result;
  if (!receipt) return { verified: false, status: "receipt_not_found" };
  if (String(receipt.transactionHash || "").toLowerCase() !== task.escrow_tx_hash.toLowerCase()) return { verified: false, status: "receipt_hash_mismatch" };
  if (String(receipt.status || "").toLowerCase() !== "0x1") return { verified: false, status: "transaction_failed" };
  let created = null;
  let funded = null;
  for (const log of Array.isArray(receipt.logs) ? receipt.logs : []) {
    const topics = Array.isArray(log?.topics) ? log.topics : [];
    if (String(log?.address || "").toLowerCase() !== DIAMOND || String(topics[1] || "").toLowerCase() !== task.task_id) continue;
    const topic = String(topics[0] || "").toLowerCase();
    const data = String(log.data || "");
    if (topic === TASK_CREATED_TOPIC && topics.length >= 4 && /^0x[0-9a-f]{256}$/i.test(data)) {
      const requester = String(task.requester || "").toLowerCase();
      const indexedRequester = String(topics[2] || "").toLowerCase();
      if (/^0x[0-9a-f]{40}$/.test(requester) && indexedRequester !== "0x" + requester.slice(2).padStart(64, "0")) continue;
      if (String(topics[3] || "").toLowerCase() !== BOUNTY_MODE_TOPIC) continue;
      created = {
        amount: BigInt("0x" + data.slice(2, 66)),
        expiry: BigInt("0x" + data.slice(66, 130)),
        stakeRequired: BigInt("0x" + data.slice(130, 194)),
        stakeBps: BigInt("0x" + data.slice(194, 258)),
      };
    }
    if (topic === ESCROW_FUNDED_TOPIC && /^0x[0-9a-f]{128}$/i.test(data)) {
      funded = {
        amount: BigInt("0x" + data.slice(2, 66)),
        component: BigInt("0x" + data.slice(66, 130)),
      };
    }
  }
  if (!created) return { verified: false, status: "task_created_event_not_found" };
  if (!funded) return { verified: false, status: "escrow_funded_event_not_found" };
  const expectedExpiry = task.expiry_time ? BigInt(Math.ceil(Date.parse(task.expiry_time) / 1000)) : -1n;
  const matches = created.amount.toString() === task.reward_base_units &&
    created.expiry === expectedExpiry && created.stakeRequired === BigInt(task.stake_required || 0) &&
    created.stakeBps === BigInt(task.stake_bps || 0) &&
    funded.amount.toString() === task.reward_base_units && funded.component === 0n;
  return { verified: matches, status: matches ? "verified" : "task_or_escrow_event_mismatch", amount_base_units: funded.amount.toString() };
}
export async function pollTaskmarket(env, fetchImpl = fetch, nowDate = new Date()) {
  const now = nowDate.toISOString();
  try {
    // The source feed is incremental in practice: tasks that disappear from its
    // open list otherwise retain stale eligible=1 records in D1 indefinitely.
    const expiredResult = await env.DB.prepare(
      `UPDATE taskmarket_work_items
       SET eligible=0,submission_window_open=0,
         eligibility_reasons_json=CASE
           WHEN expiry_time IS NULL OR julianday(expiry_time) IS NULL THEN '["expiry_missing_or_invalid"]'
           ELSE '["expired"]' END,
         execution_state=CASE
           WHEN execution_state IN ('awaiting_owner_approval','approved_awaiting_executor','blocked') THEN
             CASE WHEN expiry_time IS NULL OR julianday(expiry_time) IS NULL THEN 'blocked' ELSE 'expired' END
           ELSE execution_state END,
         updated_at=?
       WHERE eligible=1 AND (expiry_time IS NULL OR julianday(expiry_time) IS NULL OR julianday(expiry_time)<=julianday(?))`
    ).bind(now, now).run();
    const expired = Number(expiredResult.meta?.changes || 0);
    const list = await fetchJson(API + "/api/tasks?chainId=8453&status=open&limit=100&sort=newest", {}, fetchImpl);
    if (!list || !Array.isArray(list.tasks)) throw new Error("Taskmarket task-list schema changed");
    const candidates = list.tasks.map(row => normalizeTaskmarketTask(row, nowDate.getTime())).filter(Boolean)
      .sort((a,b) => Number(b.eligible) - Number(a.eligible) || Number(b.net_reward_base_units || 0) - Number(a.net_reward_base_units || 0))
      .slice(0, MAX_TASKS_PER_POLL);
    const records = [];
    for (const preview of candidates) {
      let task = preview;
      try {
        const detail = await fetchJson(API + "/api/tasks/" + encodeURIComponent(preview.task_id), {}, fetchImpl);
        if (!detail || detail.id?.toLowerCase() !== preview.task_id) throw new Error("task detail ID mismatch");
        task = normalizeTaskmarketTask(detail, nowDate.getTime()) || preview;
        if (task.escrow_tracked !== 1 || task.escrow_booked_base_units !== task.reward_base_units) {
          task.eligible = 0;
          task.qualification_reasons.push("taskmarket_escrow_record_mismatch");
        }
        if (task.eligible && task.escrow_tx_hash) {
          const escrow = await verifyTaskmarketEscrow(task, fetchImpl);
          task.escrow_verified = escrow.verified ? 1 : 0;
          task.escrow_tracked = escrow.verified ? 1 : 0;
          task.escrow_booked_base_units = escrow.amount_base_units || null;
          task.escrow_verification_status = escrow.status;
          task.escrow_verified_amount_base_units = escrow.amount_base_units || null;
          if (!escrow.verified) {
            task.eligible = 0;
            task.qualification_reasons.push("escrow_not_independently_verified:" + escrow.status);
          }
        } else {
          task.escrow_verified = 0;
          task.escrow_tracked = 0;
          task.escrow_booked_base_units = null;
          task.escrow_verification_status = "not_eligible_for_receipt_check";
          task.escrow_verified_amount_base_units = null;
        }
      } catch (error) {
        task = { ...task, eligible: 0, escrow_verified: 0, escrow_verification_status: "verification_error", escrow_verified_amount_base_units: null,
          qualification_reasons: [...task.qualification_reasons, "detail_or_receipt_check_failed:" + bounded(error?.message, 160)] };
      }
      records.push(task);
    }
    const statements = records.map(task => env.DB.prepare(
      `INSERT INTO taskmarket_work_items
      (task_id,title,description,chain_id,mode,board_state,reward_base_units,reward_usdc,net_reward_base_units,net_reward_usdc,
       escrow_tx_hash,escrow_tracked,escrow_booked_base_units,escrow_verified,escrow_verification_status,escrow_verified_amount_base_units,
       submission_count,stake_required,stake_bps,platform_fee_bps,submission_window_open,expiry_time,requester,tags_json,
       eligible,eligibility_reasons_json,first_seen_at,last_seen_at,updated_at)
      VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
      ON CONFLICT(task_id) DO UPDATE SET title=excluded.title,description=excluded.description,chain_id=excluded.chain_id,
       mode=excluded.mode,board_state=excluded.board_state,reward_base_units=excluded.reward_base_units,reward_usdc=excluded.reward_usdc,
       net_reward_base_units=excluded.net_reward_base_units,net_reward_usdc=excluded.net_reward_usdc,escrow_tx_hash=excluded.escrow_tx_hash,
       escrow_tracked=excluded.escrow_tracked,escrow_booked_base_units=excluded.escrow_booked_base_units,
       escrow_verified=excluded.escrow_verified,escrow_verification_status=excluded.escrow_verification_status,
       escrow_verified_amount_base_units=excluded.escrow_verified_amount_base_units,submission_count=excluded.submission_count,
       stake_required=excluded.stake_required,stake_bps=excluded.stake_bps,platform_fee_bps=excluded.platform_fee_bps,
       submission_window_open=excluded.submission_window_open,expiry_time=excluded.expiry_time,requester=excluded.requester,
       tags_json=excluded.tags_json,eligible=excluded.eligible,eligibility_reasons_json=excluded.eligibility_reasons_json,
       last_seen_at=excluded.last_seen_at,updated_at=excluded.updated_at`
    ).bind(task.task_id,task.title,task.description,task.chain_id,task.mode,task.board_state,task.reward_base_units,task.reward_usdc,
      task.net_reward_base_units,task.net_reward_usdc,task.escrow_tx_hash,task.escrow_tracked,task.escrow_booked_base_units,
      task.escrow_verified || 0,task.escrow_verification_status || "not_checked",task.escrow_verified_amount_base_units || null,
      task.submission_count,task.stake_required,task.stake_bps,task.platform_fee_bps,task.submission_window_open,task.expiry_time,
      task.requester,task.tags_json,task.eligible,JSON.stringify(task.qualification_reasons),now,now,now));
    if (statements.length) await env.DB.batch(statements);
    await env.DB.prepare(
      `INSERT INTO taskmarket_poll_state (source,last_success_at,last_error,last_count,last_http_status,updated_at)
       VALUES ('base-mainnet',?,NULL,?,200,?) ON CONFLICT(source) DO UPDATE SET last_success_at=excluded.last_success_at,
       last_error=NULL,last_count=excluded.last_count,last_http_status=200,updated_at=excluded.updated_at`
    ).bind(now,records.length,now).run();
    return { ok: true, discovered: records.length, qualified: records.filter(x=>x.eligible).length, expired, checked_at: now };
  } catch (error) {
    await env.DB.prepare(
      `INSERT INTO taskmarket_poll_state (source,last_success_at,last_error,last_count,last_http_status,updated_at)
       VALUES ('base-mainnet',NULL,?,0,NULL,?) ON CONFLICT(source) DO UPDATE SET last_error=excluded.last_error,updated_at=excluded.updated_at`
    ).bind(bounded(error?.message || "Taskmarket poll failed",500),now).run();
    return { ok: false, error: bounded(error?.message || "Taskmarket poll failed",500), checked_at: now };
  }
}
export async function listTaskmarketWork(env, limit = 50, qualifiedOnly = false) {
  const boundedLimit = Math.min(100, Math.max(1, Number(limit) || 50));
  const rows = await env.DB.prepare(
    `SELECT task_id,title,description,chain_id,mode,board_state,reward_usdc,net_reward_usdc,escrow_tx_hash,
      escrow_verified,escrow_verification_status,submission_count,stake_required,submission_window_open,expiry_time,
      requester,tags_json,eligible,eligibility_reasons_json,owner_approved,execution_state,first_seen_at,last_seen_at,updated_at
     FROM taskmarket_work_items ${qualifiedOnly ? "WHERE eligible=1 AND expiry_time IS NOT NULL AND julianday(expiry_time)>julianday('now')" : ""} ORDER BY eligible DESC,last_seen_at DESC LIMIT ?`
  ).bind(boundedLimit).all();
  const poll = await env.DB.prepare("SELECT * FROM taskmarket_poll_state WHERE source='base-mainnet'").first();
  return { items: (rows.results || []).map(row => ({ ...row, tags: JSON.parse(row.tags_json || "[]"), qualification_reasons: JSON.parse(row.eligibility_reasons_json || "[]"), tags_json: undefined, eligibility_reasons_json: undefined })), poll: poll || null,
    notice: "Taskmarket discovery and Base escrow receipt checks only. No wallet, identity, claim, submission, signature, or payment action is performed." };
}

const API = "https://api.taskmarket.dev";
const TASK_ID = /^0x[a-f0-9]{64}$/i;
const ADDRESS = /^0x[a-f0-9]{40}$/i;
const SIGNATURE = /^0x[a-f0-9]{130}$/i;
const TX_HASH = /^0x[a-f0-9]{64}$/i;
const MAX_DELIVERABLE_BYTES = 18000;
const FREE_TASK_TOTAL_LIMIT = 50;

function result(status, reason, extra = {}) {
  return { status, submitted: false, reason, externalActionsTaken: false, ...extra };
}

async function jsonResponse(response, label, limit = 100000) {
  if (response.status >= 300 && response.status < 400) throw new Error(label + "_redirect_rejected");
  if (!response.ok) throw new Error(label + "_http_" + response.status);
  const raw = await response.text();
  if (new TextEncoder().encode(raw).length > limit) throw new Error(label + "_response_too_large");
  try { return JSON.parse(raw); } catch { throw new Error(label + "_invalid_json"); }
}

async function apiJson(path, init = {}, fetchImpl = fetch) {
  const url = new URL(path, API);
  if (url.origin !== API) throw new Error("taskmarket_host_rejected");
  const response = await fetchImpl(url.toString(), {
    ...init,
    redirect: "manual",
    headers: {
      accept: "application/json",
      "content-type": "application/json",
      "user-agent": "AutonomousAIEconomy/0.1",
      ...(init.headers || {}),
    },
    signal: AbortSignal.timeout(12000),
  });
  return jsonResponse(response, "taskmarket");
}

/**
 * Automatic, no-owner-approval submission for a QA-passed Taskmarket Base bounty.
 * The signing key never enters this Worker: WALLET_SIGNER is an isolated signer
 * service binding. Only the first five total task submissions are considered,
 * conservatively avoiding Taskmarket's 0.001 USDC post-free-allowance fee.
 */
export async function submitTaskmarketDeliverable(env, task, deliverable, fetchImpl = fetch) {
  if (env?.TASKMARKET_SUBMISSION_ENABLED !== "true") {
    return result("not_configured", "taskmarket_submission_disabled");
  }
  if (!env?.WALLET_SIGNER || typeof env.WALLET_SIGNER.fetch !== "function" ||
      !env.WALLET_SIGNER_TOKEN || !ADDRESS.test(env.TASKMARKET_WORKER_ADDRESS || "")) {
    return result("blocked", "secure_wallet_signer_unavailable");
  }
  const taskId = String(task?.task_id || "").toLowerCase();
  if (!TASK_ID.test(taskId)) return result("blocked", "invalid_task_id");
  if (typeof deliverable !== "string" || !deliverable.trim()) return result("blocked", "empty_deliverable");
  const bytes = new TextEncoder().encode(deliverable);
  if (bytes.byteLength > MAX_DELIVERABLE_BYTES) return result("blocked", "deliverable_too_large");
  if (task?.eligible !== true && task?.eligible !== 1) return result("blocked", "task_snapshot_not_eligible");
  if (Number(task?.chain_id) !== 8453 || task?.mode !== "bounty" || task?.board_state !== "open" ||
      Number(task?.stake_required) !== 0 || Number(task?.stake_bps || 0) !== 0 ||
      !TX_HASH.test(String(task?.escrow_tx_hash || "")) || Number(task?.escrow_verified) !== 1 ||
      !Number.isFinite(Date.parse(task?.expiry_time || "")) || Date.parse(task.expiry_time) <= Date.now() ||
      !/^\d+$/.test(String(task?.reward_base_units || "")) ||
      !/^\d+$/.test(String(task?.net_reward_base_units || "")) ||
      BigInt(task.net_reward_base_units) < 1000000n) {
    return result("blocked", "task_snapshot_failed_submission_guards");
  }

  let signerHealth;
  try {
    signerHealth = await jsonResponse(await env.WALLET_SIGNER.fetch("https://wallet-signer.internal/healthz", {
      method: "GET",
      headers: { "x-aae-wallet-signer-token": env.WALLET_SIGNER_TOKEN },
      signal: AbortSignal.timeout(3000),
    }), "wallet_signer_health", 10000);
  } catch {
    return result("blocked", "wallet_signer_health_failed");
  }
  const expectedAddress = String(env.TASKMARKET_WORKER_ADDRESS).toLowerCase();
  if (signerHealth?.ok !== true || signerHealth?.chainId !== 8453 ||
      String(signerHealth?.address || "").toLowerCase() !== expectedAddress ||
      signerHealth?.signing !== "eip191") {
    return result("blocked", "wallet_signer_identity_mismatch");
  }

  let live;
  try {
    live = await apiJson("/api/tasks/" + encodeURIComponent(taskId), {}, fetchImpl);
  } catch (error) {
    return result("blocked", String(error?.message || "taskmarket_live_task_check_failed").slice(0, 160));
  }
  const liveExpiry = Date.parse(live?.expiryTime || "");
  if (!live || String(live.id || "").toLowerCase() !== taskId ||
      Number(live.chainId) !== 8453 || live.mode !== "bounty" || live.status !== "open" ||
      !Number.isFinite(liveExpiry) || liveExpiry <= Date.now() ||
      live.stakeRequired === true || Number(live.stakeBps || 0) !== 0 ||
      String(live.reward || "") !== String(task.reward_base_units) ||
      Number(live.platformFeeBps || 0) !== Number(task.platform_fee_bps || 0) ||
      String(live.requester || "").toLowerCase() !== String(task.requester || "").toLowerCase() ||
      String(live.escrowTxHash || "").toLowerCase() !== String(task.escrow_tx_hash).toLowerCase() ||
      String(live.description || "") !== String(task.description || "")) {
    return result("blocked", "live_task_terms_changed_or_closed");
  }
  const feeBps = Number(live.platformFeeBps || 0);
  if (!Number.isInteger(feeBps) || feeBps < 0 || feeBps > 10000) return result("blocked", "invalid_live_platform_fee");
  const liveNet = (BigInt(live.reward) * BigInt(10000 - feeBps) / 10000n).toString();
  if (liveNet !== String(task.net_reward_base_units)) return result("blocked", "live_net_reward_changed");
  const submissionCount = Number(live.submissionCount);
  if (!Number.isInteger(submissionCount) || submissionCount < 0 || submissionCount >= FREE_TASK_TOTAL_LIMIT) {
    return result("blocked", "task_submission_fee_threshold_reached");
  }

  let existing;
  try {
    existing = await apiJson("/api/tasks/" + encodeURIComponent(taskId) + "/submissions", {}, fetchImpl);
  } catch (error) {
    return result("blocked", String(error?.message || "submission_duplicate_check_failed").slice(0, 160));
  }
  if (!Array.isArray(existing)) return result("blocked", "submission_list_schema_mismatch");
  if (existing.some(item => String(item?.workerAddress || "").toLowerCase() === expectedAddress)) {
    return result("blocked", "worker_already_has_submission_for_task");
  }

  let signed;
  try {
    signed = await jsonResponse(await env.WALLET_SIGNER.fetch("https://wallet-signer.internal/v1/sign", {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "x-aae-wallet-signer-token": env.WALLET_SIGNER_TOKEN,
      },
      body: JSON.stringify({ chainId: 8453, message: "taskmarket:submit:" + taskId }),
      signal: AbortSignal.timeout(5000),
    }), "wallet_signer", 10000);
  } catch {
    return result("blocked", "wallet_signing_failed");
  }
  if (String(signed?.address || "").toLowerCase() !== expectedAddress ||
      !SIGNATURE.test(String(signed?.signature || ""))) {
    return result("blocked", "wallet_signature_invalid");
  }

  let base64;
  let binary = "";
  for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]);
  base64 = btoa(binary);
  let submitted;
  try {
    submitted = await apiJson("/api/tasks/" + encodeURIComponent(taskId) + "/submissions", {
      method: "POST",
      body: JSON.stringify({
        taskId,
        workerAddress: expectedAddress,
        artifacts: [{ fileName: "deliverable.md", mimeType: "text/markdown", role: "final", file: base64 }],
        signature: signed.signature,
      }),
    }, fetchImpl);
  } catch (error) {
    // Do not retry an ambiguous write automatically. Reconcile against the
    // worker's submission list before any subsequent attempt.
    return result("uncertain", String(error?.message || "submission_outcome_uncertain").slice(0, 160), {
      reconciliationRequired: true,
    });
  }
  if (submitted?.success !== true || typeof submitted?.submissionId !== "string" || !submitted.submissionId) {
    return result("uncertain", "taskmarket_submission_response_unverified", { reconciliationRequired: true });
  }
  return {
    status: "submitted",
    submitted: true,
    submissionId: submitted.submissionId,
    workerAddress: expectedAddress,
    chainId: 8453,
    externalActionsTaken: true,
    feePolicy: "only when total task submissions are below five; no paid x402 action",
  };
}

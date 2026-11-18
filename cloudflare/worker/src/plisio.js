/**
 * Isolated Plisio API adapter. Deliberately not connected to Worker routes.
 * API credentials are passed by the caller and must come from Worker secrets.
 * Never expose request URLs: Plisio requires api_key in the query string.
 */
const API_BASE = "https://api.plisio.net/api/v1";
const INVOICE_URL_HOSTS = new Set(["plisio.net", "www.plisio.net"]);

function validPositiveDecimal(value) {
  if (typeof value !== "string" || !/^(?:0|[1-9]\d*)(?:\.\d{1,8})?$/.test(value)) return false;
  return Number(value) > 0 && Number.isFinite(Number(value));
}

function sameUsdAmount(left, right) {
  if (!validPositiveDecimal(left) || !validPositiveDecimal(right)) return false;
  const [li = "0", lf = ""] = left.split(".");
  const [ri = "0", rf = ""] = right.split(".");
  return BigInt(li) * 100000000n + BigInt((lf + "00000000").slice(0, 8)) ===
    BigInt(ri) * 100000000n + BigInt((rf + "00000000").slice(0, 8));
}

function safeInvoiceUrl(value) {
  try {
    const url = new URL(value);
    return url.protocol === "https:" && INVOICE_URL_HOSTS.has(url.hostname) &&
      !url.username && !url.password ? url.toString() : null;
  } catch { return null; }
}

function callbackWithJsonFlag(value) {
  const url = new URL(value);
  if (url.protocol !== "https:" || url.username || url.password || url.hash) {
    throw new Error("Invalid Plisio callback URL");
  }
  url.searchParams.set("json", "true");
  return url.toString();
}

async function readPlisioJson(response) {
  if (!response || response.ok !== true) throw new Error("Plisio API request failed");
  let body;
  try { body = await response.json(); } catch { throw new Error("Invalid Plisio API response"); }
  if (!body || body.status !== "success" || !body.data || typeof body.data !== "object") {
    throw new Error("Plisio API did not confirm the request");
  }
  return body.data;
}

function apiUrl(path, apiKey, params = {}) {
  if (typeof apiKey !== "string" || apiKey.length < 1) throw new Error("Plisio API key is required");
  const url = new URL(`${API_BASE}${path}`);
  url.searchParams.set("api_key", apiKey);
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null) url.searchParams.set(key, String(value));
  }
  return url;
}

/** Create an invoice using server-supplied order and price data only. */
export async function createPlisioInvoice({
  apiKey, orderNumber, orderName, sourceAmount, callbackUrl, fetchImpl = fetch
}) {
  if (typeof orderNumber !== "string" || !orderNumber.trim() || orderNumber.length > 128 ||
      typeof orderName !== "string" || !orderName.trim() || orderName.length > 128 ||
      !validPositiveDecimal(sourceAmount) || typeof callbackUrl !== "string") {
    throw new Error("Invalid Plisio invoice input");
  }
  const callback = callbackWithJsonFlag(callbackUrl);
  const url = apiUrl("/invoices/new", apiKey, {
    source_currency: "USD", source_amount: sourceAmount,
    order_number: orderNumber, order_name: orderName, callback_url: callback
  });
  const data = await readPlisioJson(await fetchImpl(url.toString(), {
    method: "GET", headers: { accept: "application/json" }
  }));
  const invoiceUrl = safeInvoiceUrl(data.invoice_url);
  if (typeof data.txn_id !== "string" || !data.txn_id.trim() || !invoiceUrl) {
    throw new Error("Plisio returned an incomplete or unsafe invoice");
  }
  return Object.freeze({
    provider: "plisio", transactionId: data.txn_id,
    invoiceUrl, orderNumber, sourceCurrency: "USD", sourceAmount
  });
}

/**
 * Fetch the authoritative operation record. Callback data alone never settles
 * an order; the caller must compare this record with its own immutable order.
 */
export async function getPlisioOperation({ apiKey, transactionId, fetchImpl = fetch }) {
  if (typeof transactionId !== "string" || !/^[A-Za-z0-9_-]{1,128}$/.test(transactionId)) {
    throw new Error("Invalid Plisio transaction ID");
  }
  const data = await readPlisioJson(await fetchImpl(
    apiUrl(`/operations/${encodeURIComponent(transactionId)}`, apiKey).toString(),
    { method: "GET", headers: { accept: "application/json" } }
  ));
  if (data.id !== transactionId || data.type !== "invoice" || typeof data.status !== "string") {
    throw new Error("Plisio operation does not match the requested invoice");
  }
  return data;
}

export function normalizePlisioStatus(status) {
  switch (status) {
    case "new":
    case "pending":
    case "pending internal": return "pending";
    case "completed": return "completed";
    case "expired": return "expired";
    case "mismatch": return "mismatch";
    case "error": return "error";
    case "cancelled":
    case "cancelled duplicate": return "cancelled";
    default: return "unknown";
  }
}

/**
 * Verify the signed provider callback, then independently confirm the invoice
 * ID/type/final status through Plisio's operation endpoint. Standard Plisio
 * responses do not guarantee the white-label-only params.order_number fields,
 * so order/price matching uses the authenticated callback plus our DB order.
 */
export async function reconcilePlisioInvoice({
  apiKey, transactionId, expectedOrderNumber, expectedSourceAmount,
  callbackPayload, callbackSecret, fetchImpl = fetch
}) {
  if (typeof expectedOrderNumber !== "string" || !expectedOrderNumber ||
      !validPositiveDecimal(expectedSourceAmount) ||
      !callbackPayload || typeof callbackSecret !== "string" || !callbackSecret) {
    throw new Error("Invalid expected Plisio order or callback proof");
  }
  const callback = await verifyAndNormalizePlisioCallback(callbackPayload, callbackSecret);
  if (!callback || callback.transactionId !== transactionId) {
    throw new Error("Plisio callback signature or transaction ID is invalid");
  }
  const matched = callback.orderNumber === expectedOrderNumber &&
    callback.sourceCurrency === "USD" &&
    sameUsdAmount(callback.sourceAmount, expectedSourceAmount);
  const operation = await getPlisioOperation({ apiKey, transactionId, fetchImpl });
  const status = normalizePlisioStatus(operation.status);
  const paid = matched && callback.status === "completed" && status === "completed";
  return Object.freeze({
    provider: "plisio", transactionId, status,
    orderMatched: matched, paid,
    // A signed callback and independent authoritative operation lookup must agree.
    unlockAllowed: paid
  });
}

/** Verify JSON callback signature and expose only fields needed for reconciliation. */
export async function verifyAndNormalizePlisioCallback(payload, secret) {
  if (!await verifyPlisioJsonCallback(payload, secret)) return null;
  if (typeof payload.txn_id !== "string" || typeof payload.order_number !== "string" ||
      typeof payload.status !== "string" || payload.ipn_type !== "invoice" ||
      typeof payload.source_currency !== "string" ||
      typeof payload.source_amount !== "string" ||
      !validPositiveDecimal(payload.source_amount)) return null;
  return Object.freeze({
    transactionId: payload.txn_id,
    orderNumber: payload.order_number,
    status: normalizePlisioStatus(payload.status),
    sourceCurrency: payload.source_currency,
    sourceAmount: payload.source_amount
  });
}

function constantTimeHexEqual(left, right) {
  if (typeof left !== "string" || typeof right !== "string" ||
      !/^[0-9a-f]{40}$/i.test(left) || !/^[0-9a-f]{40}$/i.test(right)) return false;
  let difference = 0;
  const a = left.toLowerCase(), b = right.toLowerCase();
  for (let i = 0; i < 40; i++) difference |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return difference === 0;
}

export async function verifyPlisioJsonCallback(payload, secret) {
  if (!payload || typeof payload !== "object" || Array.isArray(payload) ||
      typeof secret !== "string" || secret.length === 0 ||
      typeof payload.verify_hash !== "string" ||
      !/^[0-9a-f]{40}$/i.test(payload.verify_hash)) return false;

  const unsigned = { ...payload };
  delete unsigned.verify_hash;
  let serialized;
  try { serialized = JSON.stringify(unsigned); } catch { return false; }
  if (typeof serialized !== "string") return false;

  const key = await crypto.subtle.importKey(
    "raw", new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-1" }, false, ["sign"]
  );
  const signature = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(serialized));
  const expected = [...new Uint8Array(signature)].map(byte => byte.toString(16).padStart(2, "0")).join("");
  return constantTimeHexEqual(expected, payload.verify_hash);
}

export { constantTimeHexEqual };

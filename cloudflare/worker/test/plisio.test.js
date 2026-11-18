import test from "node:test";
import assert from "node:assert/strict";
import { createHmac } from "node:crypto";
import {
  verifyPlisioJsonCallback, constantTimeHexEqual, createPlisioInvoice,
  getPlisioOperation, normalizePlisioStatus, reconcilePlisioInvoice,
  verifyAndNormalizePlisioCallback
} from "../src/plisio.js";

const SECRET = "plisio-json-callback-test-secret";
const API_KEY = "plisio-api-key-test";
function signed(payload, secret = SECRET) {
  const unsigned = { ...payload };
  delete unsigned.verify_hash;
  return { ...payload, verify_hash: createHmac("sha1", secret).update(JSON.stringify(unsigned)).digest("hex") };
}
function jsonResponse(data, status = 200) {
  return { ok: status >= 200 && status < 300, json: async () => data };
}

test("accepts documented JSON callback HMAC-SHA1 with incoming property order", async () => {
  const callback = signed({
    txn_id: "txn-123", ipn_type: "invoice", status: "completed",
    order_number: "aae-order-123", source_currency: "USD", source_amount: "5.00",
    tx_urls: ["https://explorer.example/tx/abc"]
  });
  assert.equal(await verifyPlisioJsonCallback(callback, SECRET), true);
});

test("rejects modified signed fields and wrong secret", async () => {
  const callback = signed({ txn_id: "txn-123", status: "completed", order_number: "aae-order-123" });
  callback.status = "pending";
  assert.equal(await verifyPlisioJsonCallback(callback, SECRET), false);
  assert.equal(await verifyPlisioJsonCallback(signed({ txn_id: "txn-123" }, "wrong-secret"), SECRET), false);
});

test("rejects absent, malformed, or non-object callback payloads", async () => {
  assert.equal(await verifyPlisioJsonCallback(null, SECRET), false);
  assert.equal(await verifyPlisioJsonCallback([], SECRET), false);
  assert.equal(await verifyPlisioJsonCallback({ status: "completed" }, SECRET), false);
  assert.equal(await verifyPlisioJsonCallback({ verify_hash: "bad" }, SECRET), false);
  assert.equal(await verifyPlisioJsonCallback({ verify_hash: "a".repeat(40) }, ""), false);
});

test("does not sort JSON callback keys before signature verification", async () => {
  const callback = signed({ txn_id: "txn-123", status: "completed", order_number: "aae-order-123" });
  const reordered = { order_number: callback.order_number, txn_id: callback.txn_id,
    status: callback.status, verify_hash: callback.verify_hash };
  assert.equal(await verifyPlisioJsonCallback(callback, SECRET), true);
  assert.equal(await verifyPlisioJsonCallback(reordered, SECRET), false);
});

test("signature comparison accepts hex case changes and rejects malformed values", () => {
  const hash = "0123456789abcdef0123456789abcdef01234567";
  assert.equal(constantTimeHexEqual(hash, hash.toUpperCase()), true);
  assert.equal(constantTimeHexEqual(hash, "f".repeat(40)), false);
  assert.equal(constantTimeHexEqual(hash, "short"), false);
});

test("creates a USD invoice with json callback flag and validates hosted URL", async () => {
  let requested;
  const result = await createPlisioInvoice({
    apiKey: API_KEY, orderNumber: "order-42", orderName: "Digital download",
    sourceAmount: "5.00", callbackUrl: "https://example.test/v1/plisio/callback?source=api",
    fetchImpl: async (url, options) => {
      requested = { url: new URL(url), options };
      return jsonResponse({ status: "success", data: {
        txn_id: "txn-42", invoice_url: "https://plisio.net/invoice/abc"
      } });
    }
  });
  assert.equal(requested.url.pathname, "/api/v1/invoices/new");
  assert.equal(requested.url.searchParams.get("api_key"), API_KEY);
  assert.equal(requested.url.searchParams.get("source_currency"), "USD");
  assert.equal(requested.url.searchParams.get("source_amount"), "5.00");
  assert.equal(requested.url.searchParams.get("callback_url"),
    "https://example.test/v1/plisio/callback?source=api&json=true");
  assert.equal(requested.options.method, "GET");
  assert.deepEqual(result, {
    provider: "plisio", transactionId: "txn-42", invoiceUrl: "https://plisio.net/invoice/abc",
    orderNumber: "order-42", sourceCurrency: "USD", sourceAmount: "5.00"
  });
});

test("rejects unsafe invoice URL, bad inputs, and failed provider responses", async () => {
  await assert.rejects(() => createPlisioInvoice({
    apiKey: API_KEY, orderNumber: "o1", orderName: "Item", sourceAmount: "1.00",
    callbackUrl: "http://example.test/callback", fetchImpl: async () => { throw new Error("should not call"); }
  }));
  await assert.rejects(() => createPlisioInvoice({
    apiKey: API_KEY, orderNumber: "o1", orderName: "Item", sourceAmount: "1.00",
    callbackUrl: "https://example.test/callback",
    fetchImpl: async () => jsonResponse({ status: "success", data: {
      txn_id: "txn-1", invoice_url: "https://evil.example/invoice"
    } })
  }));
  await assert.rejects(() => createPlisioInvoice({
    apiKey: API_KEY, orderNumber: "o1", orderName: "Item", sourceAmount: "0",
    callbackUrl: "https://example.test/callback", fetchImpl: async () => { throw new Error("should not call"); }
  }));
  await assert.rejects(() => createPlisioInvoice({
    apiKey: API_KEY, orderNumber: "o1", orderName: "Item", sourceAmount: "1.00",
    callbackUrl: "https://example.test/callback",
    fetchImpl: async () => jsonResponse({ status: "error", data: {} })
  }));
});

test("fetches an operation by exact ID and rejects mismatched operation type or ID", async () => {
  const operation = { id: "txn-7", type: "invoice", status: "completed" };
  const result = await getPlisioOperation({
    apiKey: API_KEY, transactionId: "txn-7",
    fetchImpl: async url => {
      const parsed = new URL(url);
      assert.equal(parsed.pathname, "/api/v1/operations/txn-7");
      return jsonResponse({ status: "success", data: operation });
    }
  });
  assert.equal(result.id, "txn-7");
  await assert.rejects(() => getPlisioOperation({
    apiKey: API_KEY, transactionId: "txn-7",
    fetchImpl: async () => jsonResponse({ status: "success", data: { ...operation, type: "cash_out" } })
  }));
});

test("reconciliation uses signed callback order data plus authoritative operation status", async () => {
  const operation = { id: "txn-9", type: "invoice", status: "completed" };
  const callbackPayload = signed({
    txn_id: "txn-9", ipn_type: "invoice", status: "completed",
    order_number: "order-9", source_currency: "USD", source_amount: "5.00"
  });
  const fetchImpl = async () => jsonResponse({ status: "success", data: operation });
  const common = { apiKey: API_KEY, transactionId: "txn-9", callbackPayload,
    callbackSecret: SECRET, expectedSourceAmount: "5.0", fetchImpl };
  const paid = await reconcilePlisioInvoice({ ...common, expectedOrderNumber: "order-9" });
  assert.equal(paid.paid, true);
  assert.equal(paid.unlockAllowed, true);

  const wrongOrder = await reconcilePlisioInvoice({ ...common, expectedOrderNumber: "other-order" });
  assert.equal(wrongOrder.paid, false);
  assert.equal(wrongOrder.unlockAllowed, false);

  const wrongAmount = await reconcilePlisioInvoice({
    ...common, expectedOrderNumber: "order-9", expectedSourceAmount: "6.00"
  });
  assert.equal(wrongAmount.paid, false);

  const notCompleted = await reconcilePlisioInvoice({
    ...common, expectedOrderNumber: "order-9",
    callbackPayload: signed({ ...callbackPayload, status: "pending" })
  });
  assert.equal(notCompleted.unlockAllowed, false);

  const wrongOperation = await reconcilePlisioInvoice({
    ...common, expectedOrderNumber: "order-9",
    fetchImpl: async () => jsonResponse({ status: "success", data: { ...operation, type: "cash_out" } })
  }).catch(error => error);
  assert.ok(wrongOperation instanceof Error);
});

test("all non-completed and unknown states fail closed", async () => {
  for (const status of ["new", "pending", "pending internal", "expired", "mismatch",
    "error", "cancelled", "cancelled duplicate", "future-status"]) {
    assert.notEqual(normalizePlisioStatus(status), "completed");
  }
  assert.equal(normalizePlisioStatus("future-status"), "unknown");
});

test("callback verification returns signed invoice metadata but never unlocks by itself", async () => {
  const callback = signed({ txn_id: "txn-11", ipn_type: "invoice", status: "completed",
    order_number: "order-11", source_currency: "USD", source_amount: "11.00" });
  const hint = await verifyAndNormalizePlisioCallback(callback, SECRET);
  assert.deepEqual(hint, { transactionId: "txn-11", orderNumber: "order-11",
    status: "completed", sourceCurrency: "USD", sourceAmount: "11.00" });
  assert.equal(hint.unlockAllowed, undefined);
  // Changing a signed field without recomputing the signature must be rejected.
  assert.equal(await verifyAndNormalizePlisioCallback({ ...callback, status: "pending" }, SECRET), null);
  assert.equal(await verifyAndNormalizePlisioCallback(signed({
    txn_id: "txn-11", status: "completed", order_number: "order-11",
    source_currency: "USD", source_amount: "11.00"
  }), SECRET), null);
});

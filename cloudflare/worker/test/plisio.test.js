import test from "node:test";
import assert from "node:assert/strict";
import { createHmac } from "node:crypto";
import { verifyPlisioJsonCallback, constantTimeHexEqual } from "../src/plisio.js";

const SECRET = "plisio-json-callback-test-secret";
function signed(payload, secret = SECRET) {
  const unsigned = { ...payload };
  delete unsigned.verify_hash;
  return { ...payload, verify_hash: createHmac("sha1", secret).update(JSON.stringify(unsigned)).digest("hex") };
}

test("accepts documented JSON callback HMAC-SHA1 with incoming property order", async () => {
  const callback = signed({
    txn_id: "txn-123", status: "completed", order_number: "aae-order-123",
    source_currency: "USD", source_amount: "5.00", tx_urls: ["https://explorer.example/tx/abc"]
  });
  assert.equal(await verifyPlisioJsonCallback(callback, SECRET), true);
});

test("rejects modified signed fields", async () => {
  const callback = signed({ txn_id: "txn-123", status: "completed", order_number: "aae-order-123" });
  callback.status = "pending";
  assert.equal(await verifyPlisioJsonCallback(callback, SECRET), false);
});

test("rejects signatures made with another secret", async () => {
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
  const reordered = {
    order_number: callback.order_number, txn_id: callback.txn_id,
    status: callback.status, verify_hash: callback.verify_hash
  };
  assert.equal(await verifyPlisioJsonCallback(callback, SECRET), true);
  assert.equal(await verifyPlisioJsonCallback(reordered, SECRET), false);
});

test("signature comparison accepts hex case changes and rejects malformed values", () => {
  const hash = "0123456789abcdef0123456789abcdef01234567";
  assert.equal(constantTimeHexEqual(hash, hash.toUpperCase()), true);
  assert.equal(constantTimeHexEqual(hash, "f".repeat(40)), false);
  assert.equal(constantTimeHexEqual(hash, "short"), false);
});

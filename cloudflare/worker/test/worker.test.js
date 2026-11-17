import test from "node:test";
import assert from "node:assert/strict";
import { createHmac } from "node:crypto";
import worker, { validFacts, validateDraft, estimateNeurons, constantTimeEqual, DAILY_NEURON_BUDGET,
  verifyNowPaymentsSignature, paymentStatusFromWebhook } from "../src/index.js";

const facts = {
  product_name: "MOBA Objective Props",
  buyer_segment: "Indie game developers and hobbyists",
  product_summary: "Five original low-poly fantasy props for game prototypes.",
  included_files: ["five individual GLB models", "combined preview GLB", "Godot 4 demo scene"],
  formats: ["GLB", "Godot 4"],
  known_limits: ["static props only", "no rigging", "no animation", "no collision shapes"],
  ai_disclosure: "AI-assisted procedural mesh generation."
};

const draft = {
  title: "MOBA Objective Props - Five Low-Poly GLB Models",
  short_description: "Five low-poly fantasy props in GLB format for Godot 4 prototypes.",
  description: "MOBA Objective Props is a small collection of five original low-poly fantasy props. Includes GLB models and a Godot 4 demo scene. Static props only, with no rigging or animation. AI-assisted procedural mesh generation.",
  tags: ["low-poly", "GLB models", "Godot assets"],
  ai_disclosure: "AI-assisted procedural mesh generation.",
  claims_to_verify: ["Inspect import scale and materials in Godot."]
};

test("facts validator accepts the real product fact sheet", () => {
  assert.equal(validFacts(facts), null);
});

test("facts validator rejects prompt injection fields and missing limitations", () => {
  assert.match(validFacts({ ...facts, publish_now: true }), /unexpected/);
  const broken = { ...facts };
  delete broken.known_limits;
  assert.match(validFacts(broken), /missing/);
});

test("draft validator accepts bounded unpublished copy", () => {
  const result = validateDraft(draft, facts);
  assert.equal(result.status, "draft");
  assert.equal(result.published, false);
  assert.equal(result.tags.length, 3);
});

test("draft validator rejects unsupported performance claims and omitted disclosure", () => {
  assert.throws(() => validateDraft({ ...draft, description: draft.description + " Best-selling and guaranteed." }, facts), /unsupported/);
  assert.throws(() => validateDraft({ ...draft, ai_disclosure: "Human-created only." }, facts), /disclosure/);
});

test("budget estimator remains bounded and uses a safety margin", () => {
  const estimate = estimateNeurons(facts);
  assert.ok(estimate > 0 && estimate < DAILY_NEURON_BUDGET);
});

test("constant time comparison handles equal and unequal secrets", () => {
  assert.equal(constantTimeEqual("secret", "secret"), true);
  assert.equal(constantTimeEqual("secret", "secreu"), false);
});


test("private API rejects absent or malformed bearer tokens before database access", async () => {
  const env = { AAE_QUEUE_TOKEN: "owner-secret-token" };
  const missing = await worker.fetch(new Request("https://example.workers.dev/v1/status"), env);
  assert.equal(missing.status, 401);
  const malformed = await worker.fetch(new Request("https://example.workers.dev/v1/status", {
    headers: { authorization: "owner-secret-token" }
  }), env);
  assert.equal(malformed.status, 401);
  const health = await worker.fetch(new Request("https://example.workers.dev/health"), env);
  assert.equal(health.status, 200);
});


function sortDeep(value) {
  if (Array.isArray(value)) return value.map(sortDeep);
  if (value && typeof value === "object") {
    return Object.keys(value).sort().reduce((out, key) => {
      out[key] = sortDeep(value[key]);
      return out;
    }, {});
  }
  return value;
}

test("NOWPayments IPN verifier matches provider HMAC-SHA512 canonicalization", async () => {
  const payload = {
    payment_id: 123456,
    payment_status: "finished",
    order_id: "order-123",
    nested: { z: 1, a: 2 },
    items: [{ b: 2, a: 1 }]
  };
  const secret = "test-ipn-secret";
  const signature = createHmac("sha512", secret)
    .update(JSON.stringify(sortDeep(payload)))
    .digest("hex");
  assert.equal(await verifyNowPaymentsSignature(payload, signature, secret), true);
  assert.equal(await verifyNowPaymentsSignature(payload, signature, "wrong-secret"), false);
  assert.equal(await verifyNowPaymentsSignature(payload, "bad", secret), false);
});

test("NOWPayments statuses settle only full finished payments", () => {
  assert.equal(paymentStatusFromWebhook({
    payment_status: "finished", pay_amount: "0.25", actually_paid: "0.25"
  }), "settled");
  assert.equal(paymentStatusFromWebhook({
    payment_status: "finished", pay_amount: "0.25", actually_paid: "0.20"
  }), "underpaid");
  assert.equal(paymentStatusFromWebhook({
    payment_status: "partially_paid", pay_amount: "0.25", actually_paid: "0.20"
  }), "underpaid");
  assert.equal(paymentStatusFromWebhook({ payment_status: "confirming" }), "processing");
  assert.equal(paymentStatusFromWebhook({ payment_status: "waiting" }), "pending");
  assert.equal(paymentStatusFromWebhook({ payment_status: "refunded" }), "refunded");
  assert.equal(paymentStatusFromWebhook({ payment_status: "unknown_future_status" }), "review");
});

class FakeD1Statement {
  constructor(db, sql) { this.db = db; this.sql = sql; this.values = []; }
  bind(...values) { this.values = values; return this; }
  async first() {
    if (this.sql.includes("SELECT event_hash FROM crypto_payment_events")) {
      return this.db.events.get(this.values[0]) || null;
    }
    if (this.sql.includes("SELECT order_id,invoice_id,price_amount,price_currency,status FROM crypto_payment_invoices")) {
      return this.db.invoice?.order_id === this.values[0] ? { ...this.db.invoice } : null;
    }
    if (this.sql.includes("SELECT status FROM crypto_payment_invoices")) {
      return this.db.invoice?.order_id === this.values[0] ? { status: this.db.invoice.status } : null;
    }
    return null;
  }
  async run() {
    if (this.sql.startsWith("INSERT OR IGNORE INTO crypto_payment_events")) {
      const [event_hash, order_id, invoice_id, payment_id, provider_status, normalized_status, received_at] = this.values;
      if (!this.db.events.has(event_hash)) {
        this.db.events.set(event_hash, { event_hash, order_id, invoice_id, payment_id, provider_status, normalized_status, received_at });
      }
      return { meta: { changes: 1 } };
    }
    if (this.sql.startsWith("UPDATE crypto_payment_invoices SET status=")) {
      const [incomingStatus, fallbackStatus, last_payment_id, actually_paid, pay_currency, updated_at, order_id] = this.values;
      if (this.db.invoice?.order_id === order_id) {
        const status = this.db.invoice.status === "refunded" ? "refunded" :
          this.db.invoice.status === "settled" && incomingStatus !== "refunded" ? "settled" : fallbackStatus;
        Object.assign(this.db.invoice, { status, last_payment_id, actually_paid, pay_currency, updated_at });
      }
      return { meta: { changes: 1 } };
    }
    return { meta: { changes: 1 } };
  }
}

test("NOWPayments IPN updates a matching invoice once and marks it settled", async () => {
  const db = {
    invoice: {
      order_id: "order-123", invoice_id: "invoice-456",
      price_amount: "5.00", price_currency: "usd", status: "pending"
    },
    events: new Map(),
    prepare(sql) { return new FakeD1Statement(this, sql); }
  };
  const payload = {
    payment_id: 98765, invoice_id: "invoice-456", payment_status: "finished",
    order_id: "order-123", price_amount: 5, price_currency: "usd",
    pay_amount: 0.25, actually_paid: 0.25, pay_currency: "btc"
  };
  const secret = "test-ipn-secret";
  const signature = createHmac("sha512", secret)
    .update(JSON.stringify(sortDeep(payload)))
    .digest("hex");
  const makeRequest = () => new Request("https://worker.example/v1/payments/nowpayments/ipn", {
    method: "POST", headers: { "content-type": "application/json", "x-nowpayments-sig": signature },
    body: JSON.stringify(payload)
  });
  const env = { NOWPAYMENTS_IPN_SECRET: secret, DB: db };
  const first = await worker.fetch(makeRequest(), env);
  assert.equal(first.status, 200);
  assert.equal((await first.json()).status, "settled");
  assert.equal(db.invoice.status, "settled");
  assert.equal(db.events.size, 1);

  const duplicate = await worker.fetch(makeRequest(), env);
  assert.equal(duplicate.status, 200);
  assert.equal((await duplicate.json()).duplicate, true);
  assert.equal(db.events.size, 1);

  const latePayload = { ...payload, payment_id: 98766, payment_status: "confirming" };
  const lateSignature = createHmac("sha512", secret)
    .update(JSON.stringify(sortDeep(latePayload)))
    .digest("hex");
  const late = await worker.fetch(new Request("https://worker.example/v1/payments/nowpayments/ipn", {
    method: "POST", headers: { "content-type": "application/json", "x-nowpayments-sig": lateSignature },
    body: JSON.stringify(latePayload)
  }), env);
  assert.equal(late.status, 200);
  assert.equal((await late.json()).status, "settled");
  assert.equal(db.invoice.status, "settled");
  assert.equal(db.events.size, 2);
});

test("NOWPayments IPN rejects an invalid signature before database access", async () => {
  const response = await worker.fetch(new Request("https://worker.example/v1/payments/nowpayments/ipn", {
    method: "POST", headers: { "content-type": "application/json", "x-nowpayments-sig": "invalid" },
    body: JSON.stringify({ order_id: "order-123" })
  }), { NOWPAYMENTS_IPN_SECRET: "secret" });
  assert.equal(response.status, 401);
});

test("crypto invoice creation stays disabled until provider secrets exist", async () => {
  const response = await worker.fetch(new Request("https://worker.example/v1/payments/nowpayments/invoices", {
    method: "POST",
    headers: { authorization: "Bearer owner-secret-token", "content-type": "application/json" },
    body: JSON.stringify({ order_id: "order-123", price_amount: "5.00" })
  }), { AAE_QUEUE_TOKEN: "owner-secret-token" });
  assert.equal(response.status, 503);
});

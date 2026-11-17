import test from "node:test";
import assert from "node:assert/strict";
import { createHmac, createHash } from "node:crypto";
import worker, { validFacts, validateDraft, estimateNeurons, extractModelText, constantTimeEqual, DAILY_NEURON_BUDGET,
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

test("Workers AI output adapter extracts documented and OpenAI-compatible text shapes", () => {
  const json = JSON.stringify({ ok: true });
  assert.equal(extractModelText({ response: json }), json);
  assert.equal(extractModelText({ choices: [{ message: { content: json } }] }), json);
  assert.equal(extractModelText({ choices: [{ text: "plain text" }] }), "plain text");
  assert.equal(extractModelText({ output_text: "output text" }), "output text");
  assert.equal(extractModelText({ response: [{ type: "text", text: "part one" }, { type: "text", text: "part two" }] }), "part onepart two");
  assert.equal(extractModelText({ reasoning: "internal reasoning only" }), null);
});

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
    if (this.sql.includes("SELECT order_id,invoice_id,price_amount,price_currency,status,product_id,agent_id FROM crypto_payment_invoices")) {
      return this.db.invoice?.order_id === this.values[0] ? { ...this.db.invoice } : null;
    }
    if (this.sql.includes("SELECT order_id,product_id,status,download_expires_at,buyer_token_hash FROM crypto_payment_invoices")) {
      return this.db.invoice?.order_id === this.values[0] ? { ...this.db.invoice } : null;
    }
    if (this.sql.includes("SELECT COUNT(*) AS sales_count")) {
      const rows = [...this.db.revenue.values()].filter(row => row.agent_id === this.values[0]);
      const sum = (predicate, field) => rows.filter(predicate).reduce((total, row) => total + (row[field] || 0), 0);
      return {
        sales_count: rows.length,
        gross_settled_minor: sum(() => true, "gross_amount_minor"),
        awaiting_reconciliation_minor: sum(row => row.status === "settled_pending_reconciliation", "gross_amount_minor"),
        reconciled_net_minor: sum(row => row.status === "reconciled", "net_amount_minor"),
        credited_to_agent_minor: sum(row => row.status === "reconciled", "agent_credit_minor")
      };
    }
    if (this.sql.includes("SELECT status FROM crypto_payment_invoices")) {
      return this.db.invoice?.order_id === this.values[0] ? { status: this.db.invoice.status } : null;
    }
    return null;
  }
  async all() {
    if (this.sql.includes("FROM agent_revenue_events WHERE agent_id=?")) {
      return { results: [...this.db.revenue.values()].filter(row => row.agent_id === this.values[0]) };
    }
    return { results: [] };
  }
  async run() {
    if (this.sql.startsWith("INSERT OR IGNORE INTO crypto_payment_invoices")) {
      const [order_id, price_amount, product_id, buyer_token_hash, agent_id, created_at, updated_at] = this.values;
      if (!this.db.invoice) {
        this.db.invoice = {
          order_id, provider: "nowpayments", price_amount, price_currency: "usd",
          status: "creating", product_id, buyer_token_hash, agent_id,
          created_at, updated_at, download_count: 0
        };
        return { meta: { changes: 1 } };
      }
      return { meta: { changes: 0 } };
    }
    if (this.sql.startsWith("UPDATE crypto_payment_invoices SET invoice_id=")) {
      const [invoice_id, checkout_url, updated_at, order_id] = this.values;
      if (this.db.invoice?.order_id === order_id) {
        Object.assign(this.db.invoice, { invoice_id, checkout_url, status: "pending", updated_at });
      }
      return { meta: { changes: 1 } };
    }
    if (this.sql.startsWith("INSERT OR IGNORE INTO agent_revenue_events")) {
      if (this.db.failRevenueInsertOnce) {
        this.db.failRevenueInsertOnce = false;
        throw new Error("simulated revenue-ledger write failure");
      }
      const [order_id, agent_id, product_id, gross_amount_minor, gross_currency,
        provider_payment_id, crypto_received_amount, crypto_currency,
        provider_outcome_amount, provider_outcome_currency, settled_at, created_at, updated_at] = this.values;
      if (!this.db.revenue.has(order_id)) {
        this.db.revenue.set(order_id, {
          order_id, agent_id, product_id, gross_amount_minor, gross_currency,
          provider_payment_id, crypto_received_amount, crypto_currency,
          provider_outcome_amount, provider_outcome_currency,
          status: "settled_pending_reconciliation", net_amount_minor: null,
          net_currency: null, agent_credit_minor: null, agent_credit_currency: null,
          settled_at, reconciled_at: null, created_at, updated_at
        });
      }
      return { meta: { changes: 1 } };
    }
    if (this.sql.startsWith("UPDATE agent_revenue_events SET status=")) {
      const [updated_at, order_id] = this.values;
      const row = this.db.revenue.get(order_id);
      if (row) {
        row.status = row.status === "reconciled" ? "refund_review" : "reversed";
        row.updated_at = updated_at;
      }
      return { meta: { changes: 1 } };
    }
    if (this.sql.startsWith("INSERT OR IGNORE INTO crypto_payment_events")) {
      const [event_hash, order_id, invoice_id, payment_id, provider_status, normalized_status, received_at] = this.values;
      if (!this.db.events.has(event_hash)) {
        this.db.events.set(event_hash, { event_hash, order_id, invoice_id, payment_id, provider_status, normalized_status, received_at });
      }
      return { meta: { changes: 1 } };
    }
    if (this.sql.startsWith("UPDATE crypto_payment_invoices SET status=")) {
      const [incomingStatus, fallbackStatus, expiryStatus, downloadExpiry,
        last_payment_id, actually_paid, pay_currency, updated_at, order_id] = this.values;
      if (this.db.invoice?.order_id === order_id) {
        const previousStatus = this.db.invoice.status;
        const status = previousStatus === "refunded" ? "refunded" :
          previousStatus === "settled" && incomingStatus !== "refunded" ? "settled" : fallbackStatus;
        const expiry = previousStatus !== "settled" && expiryStatus === "settled"
          ? downloadExpiry : this.db.invoice.download_expires_at;
        Object.assign(this.db.invoice, {
          status, download_expires_at: expiry, last_payment_id,
          actually_paid, pay_currency, updated_at
        });
      }
      return { meta: { changes: 1 } };
    }
    if (this.sql.startsWith("UPDATE crypto_payment_invoices SET download_count=")) {
      const [updated_at, order_id] = this.values;
      if (this.db.invoice?.order_id === order_id) {
        this.db.invoice.download_count += 1;
        this.db.invoice.updated_at = updated_at;
      }
      return { meta: { changes: 1 } };
    }
    return { meta: { changes: 1 } };
  }
}

function fakePaymentDb(invoice = null) {
  return {
    invoice,
    events: new Map(),
    revenue: new Map(),
    prepare(sql) { return new FakeD1Statement(this, sql); }
  };
}

function signedIPN(payload, secret) {
  return createHmac("sha512", secret)
    .update(JSON.stringify(sortDeep(payload)))
    .digest("hex");
}

test("NOWPayments IPN updates a matching invoice once and marks it settled", async () => {
  const db = fakePaymentDb({
    order_id: "order-123", invoice_id: "invoice-456",
    price_amount: "5.00", price_currency: "usd", status: "pending",
    product_id: "moba-objective-props", agent_id: "game-asset-builder", buyer_token_hash: "unused"
  });
  const payload = {
    payment_id: 98765, invoice_id: "invoice-456", payment_status: "finished",
    order_id: "order-123", price_amount: 5, price_currency: "usd",
    pay_amount: 0.25, actually_paid: 0.25, pay_currency: "btc"
  };
  const secret = "test-ipn-secret";
  const makeRequest = body => new Request("https://worker.example/v1/payments/nowpayments/ipn", {
    method: "POST", headers: { "content-type": "application/json", "x-nowpayments-sig": signedIPN(body, secret) },
    body: JSON.stringify(body)
  });
  const env = { NOWPAYMENTS_IPN_SECRET: secret, DB: db };
  const first = await worker.fetch(makeRequest(payload), env);
  assert.equal(first.status, 200);
  assert.equal((await first.json()).status, "settled");
  assert.equal(db.invoice.status, "settled");
  assert.ok(Date.parse(db.invoice.download_expires_at) > Date.now());
  assert.equal(db.events.size, 1);
  const accrued = db.revenue.get("order-123");
  assert.equal(accrued.agent_id, "game-asset-builder");
  assert.equal(accrued.gross_amount_minor, 500);
  assert.equal(accrued.status, "settled_pending_reconciliation");
  assert.equal(accrued.net_amount_minor, null);
  assert.equal(accrued.agent_credit_minor, null);

  const duplicate = await worker.fetch(makeRequest(payload), env);
  assert.equal(duplicate.status, 200);
  assert.equal((await duplicate.json()).duplicate, true);
  assert.equal(db.events.size, 1);

  const latePayload = { ...payload, payment_id: 98766, payment_status: "confirming" };
  const late = await worker.fetch(makeRequest(latePayload), env);
  assert.equal(late.status, 200);
  assert.equal((await late.json()).status, "settled");
  assert.equal(db.invoice.status, "settled");
  assert.equal(db.events.size, 2);

  const refundPayload = { ...payload, payment_id: 98767, payment_status: "refunded" };
  const refund = await worker.fetch(makeRequest(refundPayload), env);
  assert.equal(refund.status, 200);
  assert.equal((await refund.json()).status, "refunded");
  assert.equal(db.invoice.status, "refunded");
  assert.equal(db.revenue.get("order-123").status, "reversed");
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

test("public crypto checkout remains disabled until owner gates and provider credentials are present", async () => {
  const response = await worker.fetch(new Request("https://worker.example/v1/store/checkout", {
    method: "POST",
    headers: {
      origin: "https://worker.example",
      "content-type": "application/json",
      "cf-connecting-ip": "203.0.113.10"
    },
    body: "{}"
  }), {});
  assert.equal(response.status, 503);
});

test("public checkout fixes the product price and creates an invoice with a private buyer token", async () => {
  const db = fakePaymentDb();
  let providerPayload = null;
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (url, init) => {
    assert.equal(url, "https://api.nowpayments.io/v1/invoice");
    providerPayload = JSON.parse(init.body);
    return new Response(JSON.stringify({
      id: "invoice-789",
      invoice_url: "https://nowpayments.io/invoice/checkout-789"
    }), { status: 200, headers: { "content-type": "application/json" } });
  };
  try {
    const response = await worker.fetch(new Request("https://worker.example/v1/store/checkout", {
      method: "POST",
      headers: {
        origin: "https://worker.example",
        "content-type": "application/json",
        "cf-connecting-ip": "203.0.113.10"
      },
      body: "{}"
    }), {
      AAE_PUBLIC_CHECKOUT_ENABLED: "true",
      AAE_CRYPTO_ENABLEMENT_APPROVED: "true",
      NOWPAYMENTS_API_KEY: "api-test",
      NOWPAYMENTS_IPN_SECRET: "ipn-test",
      CHECKOUT_LIMITER: { limit: async () => ({ success: true }) },
      ASSETS: { fetch: async () => new Response("<html>store</html>") },
      DB: db
    });
    assert.equal(response.status, 201);
    const data = await response.json();
    assert.match(data.order_id, /^moba-/);
    assert.match(data.access_token, /^[a-f0-9]{64}$/);
    assert.equal(data.checkout_url, "https://nowpayments.io/invoice/checkout-789");
    assert.equal(data.price_amount, "5.00");
    assert.equal(db.invoice.product_id, "moba-objective-props");
    assert.equal(db.invoice.agent_id, "game-asset-builder");
    assert.equal(db.invoice.buyer_token_hash, createHash("sha256").update(data.access_token).digest("hex"));
    assert.equal(db.invoice.status, "pending");
    assert.equal(providerPayload.price_amount, 5);
    assert.equal(providerPayload.price_currency, "usd");
    assert.equal(providerPayload.order_id, data.order_id);
    assert.equal(providerPayload.success_url, "https://worker.example/?order=" + encodeURIComponent(data.order_id));
    assert.equal(providerPayload.cancel_url, "https://worker.example/?order=" + encodeURIComponent(data.order_id) + "&cancelled=1");
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("public checkout rejects cross-origin and client-supplied product prices", async () => {
  const baseEnv = {
    AAE_PUBLIC_CHECKOUT_ENABLED: "true",
    AAE_CRYPTO_ENABLEMENT_APPROVED: "true",
    NOWPAYMENTS_API_KEY: "api-test",
    NOWPAYMENTS_IPN_SECRET: "ipn-test",
    CHECKOUT_LIMITER: { limit: async () => ({ success: true }) },
    ASSETS: { fetch: async () => new Response("<html>store</html>") },
    DB: fakePaymentDb()
  };
  const crossOrigin = await worker.fetch(new Request("https://worker.example/v1/store/checkout", {
    method: "POST", headers: { origin: "https://evil.example", "content-type": "application/json", "cf-connecting-ip": "203.0.113.10" }, body: "{}"
  }), baseEnv);
  assert.equal(crossOrigin.status, 403);
  const customPrice = await worker.fetch(new Request("https://worker.example/v1/store/checkout", {
    method: "POST", headers: { origin: "https://worker.example", "content-type": "application/json", "cf-connecting-ip": "203.0.113.10" },
    body: JSON.stringify({ price_amount: "0.01", product_id: "free" })
  }), baseEnv);
  assert.equal(customPrice.status, 400);
});

test("buyer status remains locked before settlement and rejects an invalid token", async () => {
  const token = "a".repeat(64);
  const db = fakePaymentDb({
    order_id: "moba-order-123", product_id: "moba-objective-props",
    status: "pending", download_expires_at: null,
    buyer_token_hash: createHash("sha256").update(token).digest("hex")
  });
  const env = { DB: db, ASSETS: { fetch: async () => new Response("should not fetch") } };
  const status = await worker.fetch(new Request("https://worker.example/v1/store/orders/moba-order-123", {
    headers: { authorization: "Bearer " + token }
  }), env);
  assert.equal(status.status, 200);
  assert.equal((await status.json()).download_available, false);
  const wrong = await worker.fetch(new Request("https://worker.example/v1/store/orders/moba-order-123", {
    headers: { authorization: "Bearer " + "b".repeat(64) }
  }), env);
  assert.equal(wrong.status, 404);
  const locked = await worker.fetch(new Request("https://worker.example/v1/store/orders/moba-order-123/download", {
    headers: { authorization: "Bearer " + token }
  }), env);
  assert.equal(locked.status, 403);
});

test("only settled buyers can stream the protected product file", async () => {
  const token = "c".repeat(64);
  const db = fakePaymentDb({
    order_id: "moba-order-456", product_id: "moba-objective-props",
    status: "settled", download_expires_at: new Date(Date.now() + 60_000).toISOString(),
    buyer_token_hash: createHash("sha256").update(token).digest("hex"),
    download_count: 0
  });
  let requestedAsset = "";
  const env = {
    DB: db,
    ASSETS: {
      fetch: async request => {
        requestedAsset = new URL(request.url).pathname;
        return new Response(new Uint8Array([80, 75, 3, 4]), {
          status: 200, headers: { "content-length": "4" }
        });
      }
    }
  };
  const response = await worker.fetch(new Request("https://worker.example/v1/store/orders/moba-order-456/download", {
    headers: { authorization: "Bearer " + token }
  }), env);
  assert.equal(response.status, 200);
  assert.equal(response.headers.get("content-type"), "application/zip");
  assert.equal(response.headers.get("content-disposition"), 'attachment; filename="moba-objective-props.zip"');
  assert.equal(requestedAsset, "/downloads/moba-objective-props.zip");
  assert.deepEqual([...new Uint8Array(await response.arrayBuffer())], [80, 75, 3, 4]);
  assert.equal(db.invoice.download_count, 1);
});

test("direct public product-file path is blocked even when static assets are configured", async () => {
  const response = await worker.fetch(new Request("https://worker.example/downloads/moba-objective-props.zip"), {
    ASSETS: { fetch: async () => new Response("private asset") }
  });
  assert.equal(response.status, 404);
});


test("agent revenue endpoint exposes gross attribution but no unreconciled agent credit", async () => {
  const db = fakePaymentDb();
  db.revenue.set("moba-order-789", {
    order_id: "moba-order-789", agent_id: "game-asset-builder",
    product_id: "moba-objective-props", gross_amount_minor: 500,
    gross_currency: "usd", provider_payment_id: "payment-123",
    crypto_received_amount: "0.25", crypto_currency: "btc",
    provider_outcome_amount: "0.249", provider_outcome_currency: "btc",
    status: "settled_pending_reconciliation", net_amount_minor: null,
    net_currency: null, agent_credit_minor: null, agent_credit_currency: null,
    settled_at: new Date().toISOString(), reconciled_at: null
  });
  const unauthenticated = await worker.fetch(new Request("https://worker.example/v1/agents/game-asset-builder/revenue"), {
    AAE_QUEUE_TOKEN: "owner-secret-token", DB: db
  });
  assert.equal(unauthenticated.status, 401);
  const response = await worker.fetch(new Request("https://worker.example/v1/agents/game-asset-builder/revenue", {
    headers: { authorization: "Bearer owner-secret-token" }
  }), { AAE_QUEUE_TOKEN: "owner-secret-token", DB: db });
  assert.equal(response.status, 200);
  const report = await response.json();
  assert.equal(report.agent_id, "game-asset-builder");
  assert.equal(report.sales_count, 1);
  assert.equal(report.gross_settled_minor, 500);
  assert.equal(report.awaiting_reconciliation_minor, 500);
  assert.equal(report.reconciled_net_minor, 0);
  assert.equal(report.credited_to_agent_minor, 0);
  assert.equal(report.events[0].agent_credit_minor, null);
  assert.match(report.notice, /not a legal identity/);
});


test("provider callback remains retryable when agent revenue attribution fails", async () => {
  const db = fakePaymentDb({
    order_id: "order-retry-123", invoice_id: "invoice-retry-456",
    price_amount: "5.00", price_currency: "usd", status: "pending",
    product_id: "moba-objective-props", agent_id: "game-asset-builder"
  });
  db.failRevenueInsertOnce = true;
  const payload = {
    payment_id: 123456, invoice_id: "invoice-retry-456", payment_status: "finished",
    order_id: "order-retry-123", price_amount: 5, price_currency: "usd",
    pay_amount: 0.25, actually_paid: 0.25, pay_currency: "btc"
  };
  const secret = "retry-test-secret";
  const makeRequest = () => new Request("https://worker.example/v1/payments/nowpayments/ipn", {
    method: "POST",
    headers: { "content-type": "application/json", "x-nowpayments-sig": signedIPN(payload, secret) },
    body: JSON.stringify(payload)
  });
  const env = { NOWPAYMENTS_IPN_SECRET: secret, DB: db };
  await assert.rejects(() => worker.fetch(makeRequest(), env), /simulated revenue-ledger write failure/);
  assert.equal(db.invoice.status, "settled");
  assert.equal(db.events.size, 0);
  assert.equal(db.revenue.size, 0);
  const retry = await worker.fetch(makeRequest(), env);
  assert.equal(retry.status, 200);
  assert.equal((await retry.json()).status, "settled");
  assert.equal(db.events.size, 1);
  assert.equal(db.revenue.get("order-retry-123").status, "settled_pending_reconciliation");
});


test("storefront stays unpublished unless owner explicitly enables live crypto checkout", async () => {
  const assets = { fetch: async () => new Response("<html>private storefront</html>") };
  const hidden = await worker.fetch(new Request("https://worker.example/"), { ASSETS: assets });
  assert.equal(hidden.status, 404);
  const visible = await worker.fetch(new Request("https://worker.example/"), {
    ASSETS: assets,
    AAE_PUBLIC_CHECKOUT_ENABLED: "true",
    AAE_CRYPTO_ENABLEMENT_APPROVED: "true",
    NOWPAYMENTS_API_KEY: "api-test",
    NOWPAYMENTS_IPN_SECRET: "ipn-test"
  });
  assert.equal(visible.status, 200);
  assert.match(visible.headers.get("content-security-policy"), /default-src 'self'/);
  assert.equal(await visible.text(), "<html>private storefront</html>");
});

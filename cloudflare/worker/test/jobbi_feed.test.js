import test from "node:test";
import assert from "node:assert/strict";
import { normalizeJobbiFeed, syncJobbiFeed } from "../src/jobbi_feed.js";

const now = Date.parse("2026-11-21T05:00:00.000Z");
const baseGig = {
  id: "agentbounties:sample",
  url: "https://agentbounties.app/bounties/sample",
  title: "Implement a reproducible API reliability test",
  content_text: "Build a small test harness with deterministic checks and a public report.",
  date_published: "2026-11-20T10:00:00.000Z",
  date_modified: "2026-11-21T04:00:00.000Z",
  tags: ["api", "testing"],
  _jobbi: {
    source: "agentbounties",
    lane: "agent",
    reward: { amount: 2, currency: "USDC", rail: "usdc-base" },
    claims_open: true,
    payment_state: "escrowed",
    payout_grade: "A-",
    acceptance_type: "machine",
    expires: "2026-11-22T23:59:00.000Z",
    acceptance: "Deterministic tests pass.",
    extra: {},
  },
};

test("accepts fresh escrowed USDC-on-Base tasks from higher-confidence boards", () => {
  const result = normalizeJobbiFeed({ items: [baseGig] }, now);
  assert.equal(result.items.length, 1);
  assert.equal(result.items[0].reward_usd, 2);
  assert.equal(result.items[0].currency, "USDC");
  assert.equal(result.items[0].payment_rail, "usdc-base");
  assert.equal(result.items[0].payout_grade, "A-");
});

test("rejects promised, low-grade, non-USDC, low-value and closed tasks", () => {
  const result = normalizeJobbiFeed({ items: [
    {...baseGig, id:"promised", _jobbi:{...baseGig._jobbi,payment_state:"promised"}},
    {...baseGig, id:"low-grade", _jobbi:{...baseGig._jobbi,payout_grade:"C-"}},
    {...baseGig, id:"x402", _jobbi:{...baseGig._jobbi,reward:{amount:5,currency:"USDC",rail:"x402"}}},
    {...baseGig, id:"tiny", _jobbi:{...baseGig._jobbi,reward:{amount:0.5,currency:"USDC",rail:"usdc-base"}}},
    {...baseGig, id:"closed", _jobbi:{...baseGig._jobbi,claims_open:false}},
  ] }, now);
  assert.equal(result.items.length, 0);
  assert.equal(result.rejected, 5);
});

test("rejects social promotion, bonds, funding and stale tasks", () => {
  const result = normalizeJobbiFeed({ items: [
    {...baseGig, id:"social", title:"Post 10 comments on Reddit"},
    {...baseGig, id:"bond", content_text:"Claim this bounty by paying a refundable claim bond."},
    {...baseGig, id:"fund", content_text:"Create and fully fund a child bounty."},
    {...baseGig, id:"stale", date_modified:"2026-11-10T00:00:00.000Z"},
  ] }, now);
  assert.equal(result.items.length, 0);
  assert.equal(result.rejected, 4);
});

test("stores normalized candidates and records a successful feed run", async () => {
  const calls = [];
  const env = { DB: { prepare(sql) {
    return { bind(...values) { return { async run() { calls.push({sql,values}); return {meta:{changes:1}}; } }; } };
  } } };
  const feed = { items: [baseGig] };
  const result = await syncJobbiFeed(env, async (url, options) => {
    assert.match(url, /^https:\/\/jobbi\.org\/gigs\.json/);
    assert.equal(options.method, "GET");
    return {
      ok: true,
      status: 200,
      headers: { get: name => name.toLowerCase() === "date" ? "Sat, 21 Nov 2026 05:00:00 GMT" : null },
      text: async () => JSON.stringify(feed),
    };
  }, new Date(now));
  assert.equal(result.fetched, 1);
  assert.equal(result.stored, 1);
  assert.equal(calls.length, 2);
  assert.equal(calls[0].values[0], "agentbounties:sample");
  assert.match(calls[1].sql, /aae_external_bounty_feed_runs/);
  assert.equal(calls[1].values[1], "jobbi");
  assert.equal(calls[1].values[2], "success");
});

test("fails closed on feed errors and oversized responses", async () => {
  const env = { DB: { prepare() { throw new Error("telemetry unavailable"); } } };
  await assert.rejects(
    syncJobbiFeed(env, async()=>({ok:false,status:503}), new Date(now)),
    /HTTP 503/,
  );
  await assert.rejects(
    syncJobbiFeed(env, async()=>({ok:true,status:200,text:async()=>"x".repeat(1_000_001)}), new Date(now)),
    /size limit/,
  );
});

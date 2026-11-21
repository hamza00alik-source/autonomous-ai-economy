import test from "node:test";
import assert from "node:assert/strict";
import { normalizeBountyFeed, syncExternalBountyFeed } from "../src/external_bounty_feed.js";

const now = Date.parse("2026-11-21T05:00:00.000Z");
const baseItem = {
  id: "elgora:3",
  kind: "bounty",
  title: "Escrow contract review",
  source: "elgora",
  url: "https://elgora.ai/bounties/3",
  est_usd: 36,
  currency: "USDC",
  requires: ["wallet_evm"],
  deadline: "2026-11-21T23:59:00Z",
  verified_at: "2026-11-21T04:33:46Z",
  one_liner: "A scoped local review.",
  how_to_enter: ["Read the rules."],
};

test("normalizes a fresh cash bounty without treating a wallet as a stake", () => {
  const result = normalizeBountyFeed({ generated_at: "2026-11-21T04:58:00.000Z", items: [baseItem] }, now);
  assert.equal(result.items.length, 1);
  assert.equal(result.items[0].reward_usd, 36);
  assert.deepEqual(result.items[0].requirements, ["wallet_evm"]);
  assert.equal(result.items[0].source_url, baseItem.url);
});

test("marks omitted currency as an estimate rather than asserting USD or USDC", () => {
  const { currency, ...item } = baseItem;
  const result = normalizeBountyFeed({ generated_at: "2026-11-21T04:58:00.000Z", items: [item] }, now);
  assert.equal(result.items[0].currency, "USD_EQUIVALENT");
});

test("accepts feed items whose curated endpoint omits kind", () => {
  const { kind, ...curatedItem } = baseItem;
  const result = normalizeBountyFeed({ generated_at: "2026-11-21T04:58:00.000Z", items: [curatedItem] }, now);
  assert.equal(result.items.length, 1);
});

test("rejects stale feeds, expired tasks, sub-dollar and risky prerequisites", () => {
  const result = normalizeBountyFeed({
    generated_at: "2026-11-20T00:00:00.000Z",
    items: [baseItem],
  }, now);
  assert.equal(result.items.length, 0);
  assert.equal(result.reason, "stale_or_invalid_feed");

  const fresh = normalizeBountyFeed({
    generated_at: "2026-11-21T04:58:00.000Z",
    items: [
      {...baseItem, id:"expired", deadline:"2026-11-21T04:59:00Z"},
      {...baseItem, id:"stake", requires:["stake"]},
      {...baseItem, id:"tiny", est_usd:0.5},
      {...baseItem, id:"bad-url", url:"http://example.com"},
    ],
  }, now);
  assert.equal(fresh.items.length, 0);
  assert.equal(fresh.rejected, 4);
});

test("rejects social engagement and first-timer-only bounties", () => {
  const result = normalizeBountyFeed({
    generated_at: "2026-11-21T04:58:00.000Z",
    items: [
      {...baseItem, id:"social", title:"Create threads and comments on X for a KOL"},
      {...baseItem, id:"first-timer", requires:["first_timers_only"]},
    ],
  }, now);
  assert.equal(result.items.length, 0);
  assert.equal(result.rejected, 2);
});

test("stores only normalized items and preserves the source snapshot", async () => {
  const calls = [];
  const env = { DB: { prepare(sql) {
    return { bind(...values) { return { async run() { calls.push({sql,values}); return {meta:{changes:1}}; } }; } };
  } } };
  const feed = { generated_at:"2026-11-21T04:58:00.000Z", items:[baseItem] };
  const result = await syncExternalBountyFeed(env, async (url, options) => {
    assert.equal(url, "https://agent-bounty-feed.dailydollar.workers.dev/earn-now");
    assert.equal(options.method, "GET");
    return {ok:true,status:200,text:async()=>JSON.stringify(feed)};
  }, new Date(now));
  assert.equal(result.fetched, 1);
  assert.equal(result.stored, 1);
  assert.equal(calls.length, 2);
  assert.match(calls[1].sql, /aae_external_bounty_feed_runs/);
  assert.equal(calls[1].values[1], "success");
  assert.equal(calls[0].values[0], "elgora:3");
  assert.match(calls[0].values[10], /Escrow contract review/);
});

test("fails closed on HTTP and oversized feed responses", async () => {
  const env = { DB: { prepare() { throw new Error("database must not be touched"); } } };
  await assert.rejects(
    syncExternalBountyFeed(env, async()=>({ok:false,status:503}), new Date(now)),
    /HTTP 503/,
  );
  await assert.rejects(
    syncExternalBountyFeed(env, async()=>({ok:true,status:200,text:async()=>"x".repeat(256001)}), new Date(now)),
    /size limit/,
  );
});

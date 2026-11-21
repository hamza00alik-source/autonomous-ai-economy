import test from "node:test";
import assert from "node:assert/strict";
import { normalizeFranticBoard, syncFranticFeed } from "../src/frantic_feed.js";

const boardItem = {
  number: 120,
  title: "Add a valuable startup offer to Sourcey",
  price_usd: 1,
  funded: true,
  work_status: "open",
  note: "Submit one new vendor and one offer in a data-only pull request to the GitHub repository.",
  claim_slots: { capacity: 150, occupied: 10, available: 140 },
  api_url: "/v1/bounties/120",
  actions: { claim: { available: true, state: "requires_identity" } },
};
const detail = {
  ok: true,
  bounty: {
    number: 120,
    title: boardItem.title,
    description: boardItem.note,
    price_usd: 1,
    funded: true,
    work_status: "open",
    claim_progress: { capacity: 150, occupied: 10, available: 140 },
    criteria: {
      description: boardItem.note,
      verification: { requires: ["verified_email_or_runx_github_identity"] },
    },
    required_artifacts: ["pr_url"],
    posted_at: "2026-08-02T13:14:52.411Z",
  },
};

test("keeps funded, low-friction technical tasks from the Frantic board", () => {
  const result = normalizeFranticBoard({
    ok: true,
    board: { open_bounties: [
      boardItem,
      {...boardItem, number:130, title:"Answer live Reddit threads", note:"Post comments on Reddit."},
      {...boardItem, number:127, title:"Publish an original article", note:"Get a citation through outreach."},
      {...boardItem, number:97, title:"Fund a bounty", note:"Create and fund a bounty."},
      {...boardItem, number:200, price_usd:20},
      {...boardItem, number:201, claim_slots:{available:0}},
    ] },
  });
  assert.equal(result.items.length, 1);
  assert.equal(result.items[0].number, 120);
  assert.equal(result.rejected, 5);
});

test("rejects a stale board candidate when the detail endpoint has no claim slots", async () => {
  const calls = [];
  const env = { DB: { prepare(sql) {
    return { bind(...values) { return { async run() { calls.push({sql,values}); return {meta:{changes:1}}; } }; } };
  } } };
  let count = 0;
  const result = await syncFranticFeed(env, async (url) => {
    count++;
    if (count === 1) return {ok:true,status:200,text:async()=>JSON.stringify({board:{open_bounties:[boardItem]}})};
    return {ok:true,status:200,text:async()=>JSON.stringify({bounty:{...detail.bounty,claim_progress:{capacity:150,occupied:150,available:0}}})};
  }, new Date("2026-11-21T05:10:00.000Z"));
  assert.equal(result.fetched, 0);
  assert.equal(result.stored, 0);
  assert.equal(result.rejected, 1);
  assert.equal(calls.length, 1);
  assert.match(calls[0].sql, /aae_external_bounty_feed_runs/);
  assert.equal(calls[0].values[1], "frantic");
});

test("stores only after the detail endpoint confirms funded capacity", async () => {
  const calls = [];
  const env = { DB: { prepare(sql) {
    return { bind(...values) { return { async run() { calls.push({sql,values}); return {meta:{changes:1}}; } }; };
  } } };
  let count = 0;
  const result = await syncFranticFeed(env, async (url) => {
    count++;
    return {
      ok: true,
      status: 200,
      text: async () => JSON.stringify(count === 1 ? {board:{open_bounties:[boardItem]}} : detail),
    };
  }, new Date("2026-11-21T05:10:00.000Z"));
  assert.equal(result.fetched, 1);
  assert.equal(result.stored, 1);
  assert.equal(calls.length, 2);
  assert.equal(calls[0].values[0], "frantic:120");
  assert.equal(calls[0].values[5], "USDC");
  assert.equal(calls[1].values[1], "frantic");
  assert.equal(calls[1].values[2], "success");
});

test("fails closed on a board error", async () => {
  const env = { DB: { prepare() { throw new Error("telemetry unavailable"); } } };
  await assert.rejects(
    syncFranticFeed(env, async()=>({ok:false,status:503}), new Date("2026-11-21T05:10:00.000Z")),
    /HTTP 503/,
  );
});

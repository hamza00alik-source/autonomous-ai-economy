import test from "node:test";
import assert from "node:assert/strict";
import { normalizeElgoraList, syncElgoraList } from "../src/elgora_feed.js";

const now = Date.parse("2026-11-21T10:15:00.000Z");
const future = Math.floor(Date.parse("2026-11-22T23:59:00.000Z") / 1000);
const base = {
  chain_id: 8453,
  hub_address: "0x8f80d1183cd983b01b0c9ac6777cc732ec9800de",
  bounties: [
    {bounty_id:"3",status:"open",escrow:{token_address:"0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",amount:"36000000"},submission_deadline:future,submission_count:7},
    {bounty_id:"4",status:"open",escrow:{token_address:"0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",amount:"20000000"},submission_deadline:future,submission_count:10},
    {bounty_id:"5",status:"open",escrow:{token_address:"0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",amount:"25000000"},submission_deadline:future,submission_count:10},
  ],
};

test("keeps only open Base USDC bounties with estimated free submission slots", () => {
  const result = normalizeElgoraList(base, now);
  assert.equal(result.items.length, 1);
  assert.equal(result.items[0].bounty_id, "elgora:3");
  assert.equal(result.items[0].reward_usd, 36);
  assert.equal(result.items[0].currency, "USDC");
  assert.equal(result.items[0].requirements.remaining_slots_estimate, 3);
  assert.equal(result.rejected, 2);
});

test("rejects wrong chain/token, closed, expired, underfunded and full bounties", () => {
  assert.equal(normalizeElgoraList({...base, chain_id:1}, now).reason, "invalid_elgora_list_shape");
  const result = normalizeElgoraList({
    ...base,
    chain_id: 8453,
    bounties: [
      {...base.bounties[0], status:"awarded"},
      {...base.bounties[0], submission_deadline:Math.floor(now/1000)-1},
      {...base.bounties[0], escrow:{...base.bounties[0].escrow,amount:"500000"}},
      {...base.bounties[0], escrow:{...base.bounties[0].escrow,token_address:"0x0000000000000000000000000000000000000001"}},
      {...base.bounties[0], submission_count:10},
    ],
  }, now);
  assert.equal(result.items.length, 0);
  assert.equal(result.rejected, 5);
});

test("fails closed on malformed list or oversized response", async () => {
  assert.equal(normalizeElgoraList({items:[]}, now).reason, "invalid_elgora_list_shape");
  const env = { DB: { prepare() { throw new Error("telemetry unavailable"); } } };
  await assert.rejects(syncElgoraList(env, async()=>({ok:false,status:503}), new Date(now)), /HTTP 503/);
  await assert.rejects(syncElgoraList(env, async()=>({ok:true,text:async()=>"x".repeat(512001)}), new Date(now)), /size limit/);
});

test("persists the verified bounty and records the source run", async () => {
  const calls = [];
  const env = { DB: { prepare(sql) {
    return { bind(...values) { return { async run() { calls.push({sql,values}); return {meta:{changes:1}}; } }; } };
  } } };
  const result = await syncElgoraList(env, async(url, options)=>{
    assert.match(url, /^https:\/\/elgora\.ai\/api\/bounties/);
    assert.equal(options.method, "GET");
    return {ok:true,status:200,text:async()=>JSON.stringify(base)};
  }, new Date(now));
  assert.equal(result.fetched, 1);
  assert.equal(result.stored, 1);
  assert.equal(calls.length, 2);
  assert.equal(calls[0].values[0], "elgora:3");
  assert.equal(calls[0].values[1], "elgora");
  assert.equal(calls[0].values[5], "USDC");
  assert.equal(calls[1].values[1], "elgora");
});

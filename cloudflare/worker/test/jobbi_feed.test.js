import test from "node:test";
import assert from "node:assert/strict";
import { normalizeJobbiFeed, syncJobbiFeed } from "../src/jobbi_feed.js";

const now = Date.parse("2026-11-22T05:00:00.000Z");
const baseGig = {
  id: "agentbounties:sample",
  url: "https://agentbounties.app/bounties/sample",
  title: "Implement a reproducible API reliability test",
  content_text: "Build a small test harness with deterministic checks and a public report.",
  date_published: "2026-11-21T10:00:00.000Z",
  date_modified: "2026-11-22T04:00:00.000Z",
  tags: ["api", "testing"],
  _jobbi: {
    source: "agentbounties", lane: "agent",
    reward: { amount: 2, currency: "USDC", rail: "usdc-base" },
    claims_open: true, payment_state: "escrowed", payout_grade: "A-",
    acceptance_type: "machine", expires: "2026-11-23T23:59:00.000Z",
    acceptance: "Deterministic tests pass and the supplied test report is attached.", extra: {},
  },
};

test("prioritizes explicit, escrowed USDC on Base", () => {
  const result = normalizeJobbiFeed({items:[baseGig]}, now);
  assert.equal(result.items.length,1);
  assert.equal(result.items[0].payout_priority,0);
  assert.equal(result.items[0].reward_amount,2);
  assert.equal(result.items[0].reward_usd_estimate,2);
  assert.equal(result.items[0].payment_rail,"usdc-base");
  assert.equal(result.items[0].requirements.payout_network,"Base");
});

test("accepts other explicitly identified stablecoin, crypto and Payoneer rails", () => {
  const make=(id,currency,rail,amount=0.02)=>({...baseGig,id,_jobbi:{...baseGig._jobbi,reward:{amount,currency,rail}}});
  const result=normalizeJobbiFeed({items:[
    make("usdt","USDT","usdt-tron",10),
    make("eth","ETH","eth-mainnet",0.02),
    make("payoneer","USD","payoneer",25),
    make("wise","EUR","wise",25),
    {...make("arb","ARB","arb-arbitrum",12),_jobbi:{...baseGig._jobbi,reward:{amount:12,currency:"ARB",rail:"arb-arbitrum",usd_estimate:6}}},
  ]},now);
  assert.deepEqual(result.items.map(x=>x.payment_rail),["usdt-tron","arb-arbitrum","eth-mainnet","payoneer","wise"]);
  assert.equal(result.items.find(x=>x.payment_rail==="payoneer").payout_region_status,"supported_in_pakistan");
  assert.equal(result.items.find(x=>x.payment_rail==="wise").payout_region_status,"account_confirmation_required");
  assert.equal(result.items.find(x=>x.payment_rail==="arb-arbitrum").reward_usd_estimate,6);
});

test("rejects unknown, ambiguous and asset-mismatched payout rails", () => {
  const make=(id,currency,rail)=>({...baseGig,id,_jobbi:{...baseGig._jobbi,reward:{amount:5,currency,rail}}});
  const result=normalizeJobbiFeed({items:[
    make("x402","USDC","x402"),
    make("wallet","USDC","wallet"),
    make("mismatch","USDT","usdc-base"),
    make("token","OPENWORK","openwork-token"),
  ]},now);
  assert.equal(result.items.length,0);
  assert.equal(result.rejected,4);
});

test("rejects unescrowed, low-confidence, closed, stale, expired and incomplete listings", () => {
  const result=normalizeJobbiFeed({items:[
    {...baseGig,id:"promised",_jobbi:{...baseGig._jobbi,payment_state:"promised"}},
    {...baseGig,id:"low-grade",_jobbi:{...baseGig._jobbi,payout_grade:"C-"}},
    {...baseGig,id:"closed",_jobbi:{...baseGig._jobbi,claims_open:false}},
    {...baseGig,id:"stale",date_modified:"2026-11-10T00:00:00.000Z"},
    {...baseGig,id:"expired",_jobbi:{...baseGig._jobbi,expires:"2026-11-21T00:00:00.000Z"}},
    {...baseGig,id:"no-criteria",_jobbi:{...baseGig._jobbi,acceptance:""}},
  ]},now);
  assert.equal(result.items.length,0);
  assert.equal(result.rejected,6);
});

test("rejects social promotion, bonds, installation, personal data and paid APIs", () => {
  const result=normalizeJobbiFeed({items:[
    {...baseGig,id:"social",title:"Post 10 comments on Reddit"},
    {...baseGig,id:"bond",content_text:"Pay a refundable claim bond."},
    {...baseGig,id:"install",content_text:"Install this agent on the customer's production server."},
    {...baseGig,id:"pii",content_text:"Collect customer personal data and process PII."},
    {...baseGig,id:"paid-api",content_text:"Use a paid API key and subscription."},
  ]},now);
  assert.equal(result.items.length,0);
  assert.equal(result.rejected,5);
});

test("polls Jobbi at most hourly and does not fetch during the cooldown", async () => {
  const env={DB:{prepare(sql){return {first:async()=>({finished_at:new Date(now-30*60*1000).toISOString()})};}}};
  const result=await syncJobbiFeed(env,async()=>{throw new Error("must not fetch");},new Date(now));
  assert.equal(result.skipped,"hourly_rate_limit");
});

test("stores normalized candidates and records a successful feed run", async () => {
  const calls=[];
  const env={DB:{prepare(sql){
    return {bind(...values){return {async run(){calls.push({sql,values});return {meta:{changes:1}};}};},async first(){return null;}};
  }}};
  const result=await syncJobbiFeed(env,async(url,options)=>{
    assert.match(url,/^https:\/\/jobbi\.org\/gigs\.json\?lane=agent&limit=1000$/);
    assert.equal(options.method,"GET");
    return {ok:true,status:200,headers:{get:name=>name.toLowerCase()==="last-modified"?"Sun, 22 Nov 2026 05:00:00 GMT":null},text:async()=>JSON.stringify({items:[baseGig]})};
  },new Date(now));
  assert.equal(result.fetched,1);
  assert.equal(result.stored,1);
  assert.equal(calls.length,2);
  assert.equal(calls[0].values[0],"agentbounties:sample");
  assert.match(calls[0].sql,/reward_amount/);
  assert.match(calls[1].sql,/aae_external_bounty_feed_runs/);
  assert.equal(calls[1].values[1],"jobbi");
  assert.equal(calls[1].values[2],"success");
});

test("fails closed on feed errors and oversized responses", async () => {
  const env={DB:{prepare(){return {first:async()=>null,bind(){return {async run(){return {meta:{changes:1}};}};}};}}};
  await assert.rejects(syncJobbiFeed(env,async()=>({ok:false,status:503}),new Date(now)),/HTTP 503/);
  await assert.rejects(syncJobbiFeed(env,async()=>({ok:true,status:200,text:async()=>"x".repeat(1_000_001)}),new Date(now)),/size limit/);
});

import test from "node:test";
import assert from "node:assert/strict";
import {
  getCloudFinancialControls, setCloudEmergencyPause, reserveCloudAgentBudget,
  settleCloudAgentExpense, createCloudExpenseSchedule, setCloudExpenseScheduleStatus,
  runDueCloudExpenseSchedules
} from "../src/financial_controls.js";

test("cloud financial reads reject invalid owner identifiers before database access", async () => {
  let queried=false;
  const result=await getCloudFinancialControls({prepare(){queried=true;throw new Error("unexpected query");}},"bad owner id");
  assert.deepEqual(result,{ok:false,reason:"invalid_owner_id"});
  assert.equal(queried,false);
});

test("emergency pause cannot be changed by an operator or arbitrary actor", async () => {
  let batched=false;
  const result=await setCloudEmergencyPause({batch(){batched=true;}},{
    ownerId:"owner-01",actorId:"operator-01",paused:false
  });
  assert.deepEqual(result,{ok:false,reason:"owner_authorization_required"});
  assert.equal(batched,false);
});

test("budget reservation rejects malformed and expired requests before database access", async () => {
  let queried=false;
  const db={prepare(){queried=true;throw new Error("unexpected query");}};
  const result=await reserveCloudAgentBudget(db,{
    ownerId:"owner-01",agentId:"agent-01",reservationId:"reservation-01",
    idempotencyKey:"bad key",destination:"provider:exact",currency:"USD",
    amountMinor:100,expiresAt:"2020-01-01T00:00:00.000Z"
  },{now:"2026-11-19T00:00:00.000Z"});
  assert.deepEqual(result,{ok:false,reason:"invalid_reservation"});
  assert.equal(queried,false);
});

test("expense settlement refuses malformed owner and reservation identifiers", async () => {
  let queried=false;
  const result=await settleCloudAgentExpense({prepare(){queried=true;throw new Error("unexpected query");}},{
    ownerId:"invalid owner",reservationId:"reservation-01"
  });
  assert.deepEqual(result,{ok:false,reason:"invalid_expense"});
  assert.equal(queried,false);
});

test("recurring schedules enforce bounded intervals and exact required identifiers", async () => {
  let queried=false;
  const result=await createCloudExpenseSchedule({prepare(){queried=true;throw new Error("unexpected query");}},{
    ownerId:"owner-01",agentId:"agent-01",scheduleId:"schedule-01",
    destination:"provider:exact",currency:"USD",amountMinor:100,
    intervalSeconds:59,nextDueAt:"2026-11-20T00:00:00.000Z"
  },{now:"2026-11-19T00:00:00.000Z"});
  assert.deepEqual(result,{ok:false,reason:"invalid_schedule"});
  assert.equal(queried,false);
});

test("schedule status changes accept only explicit lifecycle states", async () => {
  let queried=false;
  const result=await setCloudExpenseScheduleStatus({prepare(){queried=true;throw new Error("unexpected query");}},{
    ownerId:"owner-01",scheduleId:"schedule-01",status:"deleted"
  });
  assert.deepEqual(result,{ok:false,reason:"invalid_schedule_control"});
  assert.equal(queried,false);
});

test("cloud scheduler fails closed when no explicit owner unpause exists", async () => {
  const calls=[];
  const db={prepare(sql){calls.push(sql);return {bind(){return {first:async()=>null};}};},async batch(){return [];}};
  const result=await runDueCloudExpenseSchedules(db,"owner-01",{now:"2026-11-19T00:00:00.000Z"});
  assert.deepEqual(result,{settled:0,blocked:0,skipped:0,expired:0,paused:true});
  assert.equal(calls.length,3);
});


test("cloud policy registration verifies local owner signature and writes policy plus audit atomically", async () => {
  const { registerCloudSignedFinancialPolicy } = await import("../src/financial_controls.js");
  const { canonicalizeFinancialPolicy, financialPublicKeyFingerprint } = await import("../src/financial_policy_auth.js");
  const pair=await crypto.subtle.generateKey({name:"Ed25519"},true,["sign","verify"]);
  const jwk=await crypto.subtle.exportKey("jwk",pair.publicKey);
  const fingerprint=await financialPublicKeyFingerprint(jwk);
  const policy={policy_id:"policy-cloud-01",version:1,owner_id:"owner-01",agent_id:"agent-01",currency:"USD",
    per_transaction_limit_minor:1000,daily_spend_limit_minor:5000,allowed_destinations:["provider:exact"]};
  const canonicalPayload=canonicalizeFinancialPolicy(policy);
  const signature=new Uint8Array(await crypto.subtle.sign({name:"Ed25519"},pair.privateKey,new TextEncoder().encode(canonicalPayload)));
  let batches=0;
  const relationship={owner_id:"owner-01",owner_type:"owner",owner_status:"active",signer_id:"operator-01",
    signer_type:"operator",signer_status:"active",signer_owner_id:"owner-01",key_fingerprint:fingerprint,
    public_key_jwk:JSON.stringify(jwk),agent_id:"agent-01",agent_type:"agent",agent_status:"active",
    agent_owner_id:"owner-01",operator_id:"operator-01"};
  const db={
    prepare(sql){return {bind(){return {first:async()=>sql.includes("MAX(version)")?{version:null}:relationship};}};},
    async batch(statements){batches++;assert.equal(statements.length,3);return [];}
  };
  const result=await registerCloudSignedFinancialPolicy(db,{ownerId:"owner-01",policy,canonicalPayload,
    signatureBase64Url:base64url(signature),signerKeyFingerprint:fingerprint,now:"2026-11-19T00:00:00.000Z"});
  assert.equal(result.ok,true);
  assert.equal(result.version,1);
  assert.equal(batches,1);
});

test("cloud policy registration rejects invalid signatures and stale policy versions", async () => {
  const { registerCloudSignedFinancialPolicy } = await import("../src/financial_controls.js");
  const { canonicalizeFinancialPolicy, financialPublicKeyFingerprint } = await import("../src/financial_policy_auth.js");
  const pair=await crypto.subtle.generateKey({name:"Ed25519"},true,["sign","verify"]);
  const jwk=await crypto.subtle.exportKey("jwk",pair.publicKey);
  const fingerprint=await financialPublicKeyFingerprint(jwk);
  const policy={policy_id:"policy-cloud-02",version:2,owner_id:"owner-01",agent_id:"agent-01",currency:"USD",
    per_transaction_limit_minor:1000,daily_spend_limit_minor:5000,allowed_destinations:["provider:exact"]};
  const canonicalPayload=canonicalizeFinancialPolicy(policy);
  const signature=new Uint8Array(await crypto.subtle.sign({name:"Ed25519"},pair.privateKey,new TextEncoder().encode(canonicalPayload)));
  let batches=0;
  const relationship={owner_id:"owner-01",owner_type:"owner",owner_status:"active",signer_id:"operator-01",
    signer_type:"operator",signer_status:"active",signer_owner_id:"owner-01",key_fingerprint:fingerprint,
    public_key_jwk:JSON.stringify(jwk),agent_id:"agent-01",agent_type:"agent",agent_status:"active",
    agent_owner_id:"owner-01",operator_id:"operator-01"};
  const db={prepare(sql){return {bind(){return {first:async()=>sql.includes("MAX(version)")?{version:2}:relationship};}};},async batch(){batches++;}};
  const bad=await registerCloudSignedFinancialPolicy(db,{ownerId:"owner-01",policy,canonicalPayload,
    signatureBase64Url:base64url(signature).slice(1),signerKeyFingerprint:fingerprint});
  assert.equal(bad.ok,false);
  assert.equal(batches,0);
  const stale=await registerCloudSignedFinancialPolicy(db,{ownerId:"owner-01",policy,canonicalPayload,
    signatureBase64Url:base64url(signature),signerKeyFingerprint:fingerprint});
  assert.deepEqual(stale,{ok:false,reason:"policy_version_must_increase"});
  assert.equal(batches,0);
});

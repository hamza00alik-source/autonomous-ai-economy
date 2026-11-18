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
  const db={prepare(sql){calls.push(sql);return {bind(){return {first:async()=>null};}};}};
  const result=await runDueCloudExpenseSchedules(db,"owner-01",{now:"2026-11-19T00:00:00.000Z"});
  assert.deepEqual(result,{settled:0,blocked:0,skipped:0,paused:true});
  assert.equal(calls.length,1);
});

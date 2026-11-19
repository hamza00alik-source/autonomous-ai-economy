import test from "node:test";
import assert from "node:assert/strict";
import { postCloudJournalTransaction, validateCloudJournalCommand } from "../src/financial_ledger.js";

const command = () => ({
  owner_id: "owner-01",
  actor_id: "operator-01",
  idempotency_key: "expense-2026-0001",
  source_type: "expense",
  source_reference: "expense-run-0001",
  currency: "USD",
  description: "Simulated storage expense",
  postings: [
    { account_id: "agent-operating-01", direction: "debit", amount_minor: 1200 },
    { account_id: "operating-expense-01", direction: "credit", amount_minor: 1200 }
  ]
});
class Statement {
  constructor(db,sql){this.db=db;this.sql=sql;this.values=[];}
  bind(...values){this.values=values;return this;}
  async first(){
    if(this.sql.includes("FROM financial_journal_transactions WHERE idempotency_key")) return this.db.existing;
    return null;
  }
  async all(){
    if(this.sql.includes("FROM financial_accounts")) return {results:this.db.accounts};
    return {results:[]};
  }
}
class FakeD1 {
  constructor(){
    this.existing=null;
    this.accounts=[
      {account_id:"agent-operating-01",owner_id:"owner-01",currency:"USD",status:"active"},
      {account_id:"operating-expense-01",owner_id:"owner-01",currency:"USD",status:"active"}
    ];
    this.batches=[];
    this.failBatch=false;
    this.raceRow=null;
  }
  prepare(sql){return new Statement(this,sql);}
  async batch(statements){
    this.batches.push(statements);
    if(this.failBatch){this.existing=this.raceRow;throw new Error("simulated D1 batch race");}
    const insert=statements[0];
    this.existing={transaction_id:insert.values[0],payload_hash:insert.values[3],status:"posted"};
    return statements.map(()=>({success:true}));
  }
}

test("balanced cloud journal command passes strict validation",()=>{
  assert.equal(validateCloudJournalCommand(command()),null);
});
test("cloud journal rejects unbalanced amounts and duplicate accounts",()=>{
  const unbalanced=command();unbalanced.postings[0].amount_minor=1199;
  assert.equal(validateCloudJournalCommand(unbalanced),"unbalanced_journal_transaction");
  const duplicate=command();duplicate.postings[1].account_id=duplicate.postings[0].account_id;
  assert.equal(validateCloudJournalCommand(duplicate),"duplicate_posting_account");
});
test("cloud journal rejects unsafe integer amounts and unknown source types",()=>{
  const overflow=command();overflow.postings[0].amount_minor=Number.MAX_SAFE_INTEGER+1;
  assert.equal(validateCloudJournalCommand(overflow),"invalid_posting_amount");
  const source=command();source.source_type="borrow";
  assert.equal(validateCloudJournalCommand(source),"invalid_source_type");
});
test("cloud journal refuses missing, foreign, frozen or wrong-currency accounts",async()=>{
  for(const mutate of [
    db=>{db.accounts.pop();},
    db=>{db.accounts[0].owner_id="other-owner";},
    db=>{db.accounts[0].status="frozen";},
    db=>{db.accounts[0].currency="EUR";}
  ]){
    const db=new FakeD1();mutate(db);
    const result=await postCloudJournalTransaction(db,command());
    assert.deepEqual(result,{ok:false,reason:db.accounts.length===1?"journal_account_not_found":"journal_account_not_authorized"});
    assert.equal(db.batches.length,0);
  }
});
test("cloud journal posts transaction, postings and audit in one D1 batch",async()=>{
  const db=new FakeD1();
  const result=await postCloudJournalTransaction(db,command(),{now:"2026-11-19T00:00:00.000Z",transactionId:"txn-01",eventId:"audit-01"});
  assert.deepEqual(result,{ok:true,idempotent:false,transaction_id:"txn-01"});
  assert.equal(db.batches.length,1);
  assert.equal(db.batches[0].length,4);
  assert.match(db.batches[0][0].sql,/INSERT INTO financial_journal_transactions/);
  assert.equal(db.batches[0][1].values[2],"agent-operating-01");
  assert.equal(db.batches[0][2].values[2],"operating-expense-01");
  assert.match(db.batches[0][3].sql,/INSERT INTO financial_audit_events/);
});
test("cloud journal idempotent replay returns the original transaction without another batch",async()=>{
  const db=new FakeD1();
  const first=await postCloudJournalTransaction(db,command(),{transactionId:"txn-original"});
  const second=await postCloudJournalTransaction(db,command(),{transactionId:"txn-duplicate"});
  assert.equal(first.transaction_id,"txn-original");
  assert.deepEqual(second,{ok:true,idempotent:true,transaction_id:"txn-original"});
  assert.equal(db.batches.length,1);
});
test("cloud journal rejects reuse of an idempotency key with changed terms",async()=>{
  const db=new FakeD1();
  await postCloudJournalTransaction(db,command());
  const changed=command();changed.postings[0].amount_minor=1100;changed.postings[1].amount_minor=1100;
  const result=await postCloudJournalTransaction(db,changed);
  assert.deepEqual(result,{ok:false,reason:"idempotency_key_reused_with_different_terms"});
  assert.equal(db.batches.length,1);
});
test("cloud journal resolves an uncertain duplicate batch by reading back the same payload hash",async()=>{
  const db=new FakeD1();
  const input=command();
  const { createHash }=await import("node:crypto");
  const normalized={
    owner_id:input.owner_id,actor_id:input.actor_id,idempotency_key:input.idempotency_key,
    source_type:input.source_type,source_reference:input.source_reference,currency:input.currency,
    description:input.description,postings:input.postings
  };
  const sort=value=>Array.isArray(value)?value.map(sort):value&&typeof value==="object"?Object.keys(value).sort().reduce((o,k)=>(o[k]=sort(value[k]),o),{}):value;
  const hash=createHash("sha256").update(JSON.stringify(sort(normalized))).digest("hex");
  db.failBatch=true;db.raceRow={transaction_id:"txn-raced",payload_hash:hash,status:"posted"};
  const result=await postCloudJournalTransaction(db,input);
  assert.deepEqual(result,{ok:true,idempotent:true,transaction_id:"txn-raced"});
});

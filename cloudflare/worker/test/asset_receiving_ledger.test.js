import test from "node:test";
import assert from "node:assert/strict";
import { postConfirmedReceivingPayment } from "../src/asset_receiving_ledger.js";

const invoice={
  invoice_id:"inv-123",owner_id:"owner-123",agent_id:"agent-123",wallet_id:"wallet-123",
  amount_minor:2_500_000,network:"base-mainnet",chain_id:8453,asset_code:"USDC",
  token_contract:"0x833589fcd6ed6e08f4c7c32d4f71b54bda02913",status:"confirmed"
};
const evidence={
  observation_id:"obs-123",tx_hash:"0x"+"a".repeat(64),block_number:100,block_hash:"0x"+"b".repeat(64),
  amount_minor:2_500_000,status:"confirmed"
};
class FakeDb {
  constructor(inv=invoice,obs=evidence){this.invoice=inv;this.evidence=obs;this.batches=[];this.firstCalls=0;}
  prepare(sql){const db=this;return {sql,args:[],bind(...args){this.args=args;return this;},
    async first(){
      if(sql.includes("FROM financial_receiving_invoices"))return db.invoice;
      if(sql.includes("FROM financial_receiving_payment_observations"))return db.evidence;
      if(sql.includes("FROM financial_asset_journal_transactions"))return null;
      return null;
    },
    async all(){
      if(sql.includes("FROM financial_asset_accounts"))return {results:[
        {account_id:"pending-wallet-account",account_type:"agent_pending_custody",status:"active"},
        {account_id:"pending-revenue-account",account_type:"agent_pending_revenue",status:"active"}
      ]};
      return {results:[]};
    }
  };}
  async batch(statements){this.batches.push(statements);return [];}
}
test("does not journal a receipt unless invoice and immutable chain evidence are confirmed",async()=>{
  const db=new FakeDb({...invoice,status:"review"},evidence);
  const result=await postConfirmedReceivingPayment(db,{ownerId:"owner-123",agentId:"agent-123",invoiceId:"inv-123"});
  assert.deepEqual(result,{ok:false,reason:"confirmed_supported_invoice_required"});
  assert.equal(db.batches.length,0);
});
test("does not journal when confirmed observation amount differs from invoice",async()=>{
  const db=new FakeDb(invoice,{...evidence,amount_minor:1});
  const result=await postConfirmedReceivingPayment(db,{ownerId:"owner-123",agentId:"agent-123",invoiceId:"inv-123"});
  assert.deepEqual(result,{ok:false,reason:"exact_confirmed_chain_evidence_required"});
  assert.equal(db.batches.length,0);
});
test("posts a balanced USDC journal into pending custody, never an available account",async()=>{
  const db=new FakeDb();
  const result=await postConfirmedReceivingPayment(db,{ownerId:"owner-123",agentId:"agent-123",invoiceId:"inv-123"});
  assert.equal(result.ok,true);
  assert.equal(result.status,"pending_wallet_control");
  assert.equal(result.amount_minor,2_500_000);
  assert.equal(db.batches.length,2);
  const journal=db.batches[1];
  assert.equal(journal.length,4);
  assert.match(journal[0].sql,/financial_asset_journal_transactions/);
  assert.match(journal[1].sql,/financial_asset_journal_postings/);
  assert.match(journal[2].sql,/financial_asset_journal_postings/);
  assert.deepEqual(journal[1].args.slice(0,2),[result.transaction_id,"pending-wallet-account"]);
  assert.deepEqual(journal[2].args.slice(0,2),[result.transaction_id,"pending-revenue-account"]);
  assert.equal(journal[1].args[2],2_500_000);
  assert.equal(journal[2].args[2],2_500_000);
});

import test from "node:test";
import assert from "node:assert/strict";
import { inspectBaseUsdcReceipt } from "../src/base_chain_verifier.js";

const recipient="0x1111111111111111111111111111111111111111";
const topicTo="0x"+recipient.slice(2).padStart(64,"0");
const transferTopic="0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef";
const contract="0x833589fcD6eDb6E08f4c7C32D4f71b54bdA02913";
const invoice={receiving_address:recipient,amount_minor:1_500_000,expires_at:"2026-11-20T00:00:00.000Z"};
function fixture({amount="0x16e360",block="0x64",finalized="0x70",timestamp="0x691e0a00",status="0x1",hash="0x"+"a".repeat(64)}={}) {
  const receipt={transactionHash:"0x"+"b".repeat(64),status,blockNumber:block,blockHash:hash,logs:[
    {address:contract,topics:[transferTopic,"0x"+"0".repeat(64),topicTo],data:amount,logIndex:"0x2"}
  ]};
  return {chainId:"0x2105",receipt,receiptBlock:{number:block,hash,timestamp},finalizedBlock:{number:finalized}};
}
test("confirms exact USDC transfer only after canonical block is finalized",()=>{
  const result=inspectBaseUsdcReceipt({...fixture({timestamp:"0x691e0a00"}),invoice});
  assert.equal(result.ok,true);
  assert.equal(result.status,"confirmed");
  assert.equal(result.amount_minor,1_500_000);
});
test("does not confirm a transaction before finalized block reaches it",()=>{
  const result=inspectBaseUsdcReceipt({...fixture({block:"0x70",finalized:"0x69"}),invoice});
  assert.equal(result.reason,"pending_finality");
});
test("rejects wrong chain and failed transaction",()=>{
  assert.equal(inspectBaseUsdcReceipt({...fixture(),invoice,chainId:"0x1"}).reason,"wrong_chain");
  assert.equal(inspectBaseUsdcReceipt({...fixture({status:"0x0"}),invoice}).reason,"transaction_failed");
});
test("detects amount mismatch and late payments for manual review",()=>{
  assert.equal(inspectBaseUsdcReceipt({...fixture({amount:"0x1"}),invoice}).status,"review");
  const late={...invoice,expires_at:"2020-01-01T00:00:00.000Z"};
  assert.equal(inspectBaseUsdcReceipt({...fixture(),invoice:late}).reason,"payment_after_invoice_expiry");
});
test("rejects noncanonical block hash and unrelated token logs",()=>{
  const bad=fixture();bad.receiptBlock.hash="0x"+"c".repeat(64);
  assert.equal(inspectBaseUsdcReceipt({...bad,invoice}).reason,"receipt_block_not_canonical");
  const unrelated=fixture();unrelated.receipt.logs[0].address="0x"+"2".repeat(40);
  assert.equal(inspectBaseUsdcReceipt({...unrelated,invoice}).reason,"matching_usdc_transfer_not_found");
});

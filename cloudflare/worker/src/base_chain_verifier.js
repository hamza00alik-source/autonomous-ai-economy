const USDC_BASE = "0x833589fcD6eDb6E08f4c7C32D4f71b54bdA02913".toLowerCase();
const TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef";
const TX_HASH = /^0x[a-fA-F0-9]{64}$/;
function hexBigInt(value) {
  if(typeof value!=="string"||!/^0x[0-9a-fA-F]+$/.test(value)) return null;
  try{return BigInt(value);}catch{return null;}
}
export function inspectBaseUsdcReceipt({chainId,receipt,receiptBlock,finalizedBlock,invoice}={}) {
  if(chainId!=="0x2105") return {ok:false,reason:"wrong_chain"};
  if(!receipt||!receipt.blockNumber||!receipt.blockHash||!Array.isArray(receipt.logs)) return {ok:false,reason:"transaction_not_found"};
  if(receipt.status!=="0x1") return {ok:false,reason:"transaction_failed"};
  const blockNumber=hexBigInt(receipt.blockNumber);
  const finalizedNumber=hexBigInt(finalizedBlock?.number);
  if(blockNumber===null||finalizedNumber===null) return {ok:false,reason:"finality_unavailable"};
  if(finalizedNumber<blockNumber) return {ok:false,reason:"pending_finality"};
  if(!receiptBlock||String(receiptBlock.hash||"").toLowerCase()!==String(receipt.blockHash).toLowerCase()) return {ok:false,reason:"receipt_block_not_canonical"};
  const invoiceAddress=String(invoice?.receiving_address||"").toLowerCase();
  if(!/^0x[a-f0-9]{40}$/.test(invoiceAddress)||!Number.isSafeInteger(invoice?.amount_minor)||invoice.amount_minor<=0) return {ok:false,reason:"invalid_invoice"};
  const recipientTopic="0x"+invoiceAddress.slice(2).padStart(64,"0");
  let amount=0n;
  const logIndices=[];
  for(const log of receipt.logs){
    if(String(log.address||"").toLowerCase()!==USDC_BASE) continue;
    const topics=Array.isArray(log.topics)?log.topics:[];
    if(String(topics[0]||"").toLowerCase()!==TRANSFER_TOPIC||String(topics[2]||"").toLowerCase()!==recipientTopic) continue;
    if(typeof log.data!=="string"||!/^0x[0-9a-fA-F]{64}$/.test(log.data)) continue;
    amount+=BigInt(log.data);
    if(!Number.isSafeInteger(Number(amount))) return {ok:false,reason:"amount_overflow"};
    const index=hexBigInt(log.logIndex);
    if(index!==null) logIndices.push(Number(index));
  }
  if(amount===0n) return {ok:false,reason:"matching_usdc_transfer_not_found"};
  const received=Number(amount);
  const blockTimestamp=hexBigInt(receiptBlock.timestamp);
  if(blockTimestamp===null) return {ok:false,reason:"invalid_receipt_block_timestamp"};
  const receivedAt=new Date(Number(blockTimestamp)*1000).toISOString();
  const timely=Date.parse(receivedAt)<=Date.parse(invoice.expires_at);
  const exact=received===invoice.amount_minor;
  return {
    ok:true,status:exact&&timely?"confirmed":"review",
    reason:!exact?"amount_mismatch":!timely?"payment_after_invoice_expiry":null,
    amount_minor:received,block_number:Number(blockNumber),block_hash:receipt.blockHash.toLowerCase(),
    received_at:receivedAt,matched_log_indices:logIndices
  };
}
async function rpc(rpcUrl,method,params) {
  const response=await fetch(rpcUrl,{method:"POST",headers:{"content-type":"application/json"},
    body:JSON.stringify({jsonrpc:"2.0",id:1,method,params})});
  if(!response.ok) throw new Error("Base RPC request failed with HTTP "+response.status);
  const data=await response.json();
  if(data?.error||!("result" in (data||{}))) throw new Error("Base RPC returned an invalid "+method+" response");
  return data.result;
}
export async function verifyBaseUsdcInvoicePayment(db,{ownerId,agentId,invoiceId,txHash,rpcUrl,now=new Date().toISOString()}={}) {
  if(typeof ownerId!=="string"||typeof agentId!=="string"||typeof invoiceId!=="string"||!TX_HASH.test(txHash||"")) return {ok:false,reason:"invalid_verification_request"};
  let endpoint;
  try{endpoint=new URL(rpcUrl);}catch{return {ok:false,reason:"base_rpc_not_configured"};}
  if(endpoint.protocol!=="https:") return {ok:false,reason:"https_base_rpc_required"};
  const invoice=await db.prepare("SELECT invoice_id,owner_id,agent_id,amount_minor,network,chain_id,token_contract,receiving_address,expires_at,status FROM financial_receiving_invoices WHERE invoice_id=? AND owner_id=? AND agent_id=?")
    .bind(invoiceId,ownerId,agentId).first();
  if(!invoice) return {ok:false,reason:"invoice_not_found"};
  const prior=await db.prepare("SELECT invoice_id,tx_hash,status,amount_minor,block_number,block_hash FROM financial_receiving_payment_observations WHERE network=? AND tx_hash=?")
    .bind("base-mainnet",txHash.toLowerCase()).first();
  if(prior) return prior.invoice_id===invoiceId
    ? {ok:true,idempotent:true,status:prior.status,observation:prior}
    : {ok:false,reason:"transaction_already_bound_to_another_invoice"};
  if(invoice.status!=="awaiting_payment") return {ok:false,reason:"invoice_not_awaiting_payment"};
  if(invoice.network!=="base-mainnet"||invoice.chain_id!==8453||String(invoice.token_contract).toLowerCase()!==USDC_BASE) return {ok:false,reason:"unsupported_invoice_asset"};
  const [chainId,receipt]=await Promise.all([rpc(endpoint.toString(),"eth_chainId",[]),rpc(endpoint.toString(),"eth_getTransactionReceipt",[txHash.toLowerCase()])]);
  if(chainId!=="0x2105") return {ok:false,reason:"wrong_chain"};
  if(!receipt) return {ok:false,reason:"transaction_not_found"};
  if(String(receipt.transactionHash||"").toLowerCase()!==txHash.toLowerCase()) return {ok:false,reason:"transaction_hash_mismatch"};
  const [receiptBlock,finalizedBlock]=await Promise.all([
    rpc(endpoint.toString(),"eth_getBlockByNumber",[receipt.blockNumber,false]),
    rpc(endpoint.toString(),"eth_getBlockByNumber",["finalized",false])
  ]);
  const inspected=inspectBaseUsdcReceipt({chainId,receipt,receiptBlock,finalizedBlock,invoice});
  if(!inspected.ok) return inspected;
  const observationId=crypto.randomUUID();
  const eventId=crypto.randomUUID();
  const status=inspected.status;
  const evidence={chain_id:8453,token_contract:USDC_BASE,tx_hash:txHash.toLowerCase(),
    block_number:inspected.block_number,block_hash:inspected.block_hash,received_at:inspected.received_at,
    amount_minor:inspected.amount_minor,matched_log_indices:inspected.matched_log_indices};
  try{
    await db.batch([
      db.prepare("INSERT INTO financial_receiving_payment_observations(observation_id,owner_id,agent_id,invoice_id,network,tx_hash,block_number,block_hash,amount_minor,matched_log_indices_json,status,evidence_json,observed_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)")
        .bind(observationId,ownerId,agentId,invoiceId,"base-mainnet",txHash.toLowerCase(),inspected.block_number,inspected.block_hash,
          inspected.amount_minor,JSON.stringify(inspected.matched_log_indices),status,JSON.stringify(evidence),now),
      db.prepare("UPDATE financial_receiving_invoices SET status=?,updated_at=? WHERE invoice_id=? AND status='awaiting_payment'")
        .bind(status,now,invoiceId),
      db.prepare("INSERT INTO financial_audit_events(event_id,owner_id,actor_id,event_type,target_type,target_id,request_id,details_json,created_at) VALUES(?,?,?,?,?,?,?,?,?)")
        .bind(eventId,ownerId,ownerId,status==="confirmed"?"financial.receiving_payment_confirmed":"financial.receiving_payment_review",
          "receiving_invoice",invoiceId,txHash.toLowerCase(),JSON.stringify(evidence),now)
    ]);
  }catch(error){
    const raced=await db.prepare("SELECT invoice_id,tx_hash,status,amount_minor,block_number,block_hash FROM financial_receiving_payment_observations WHERE network=? AND tx_hash=?")
      .bind("base-mainnet",txHash.toLowerCase()).first();
    if(raced&&raced.invoice_id===invoiceId) return {ok:true,idempotent:true,status:raced.status,observation:raced};
    if(raced) return {ok:false,reason:"transaction_already_bound_to_another_invoice"};
    throw error;
  }
  return {ok:true,idempotent:false,invoice_id:invoiceId,tx_hash:txHash.toLowerCase(),...inspected,
    notice:"This confirms the exact Base USDC transfer at the RPC provider's finalized block. It does not credit the financial ledger or agent budget."};
}

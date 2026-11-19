const ASSET = Object.freeze({
  network:"base-mainnet",chain_id:8453,asset_code:"USDC",
  token_contract:"0x833589fcd6ed6e08f4c7c32d4f71b54bda02913",token_decimals:6
});
function sorted(value){
  if(Array.isArray(value))return value.map(sorted);
  if(value&&typeof value==="object")return Object.keys(value).sort().reduce((out,key)=>{out[key]=sorted(value[key]);return out;},{});
  return value;
}
const canonical=value=>JSON.stringify(sorted(value));
async function hash(value){
  const bytes=await crypto.subtle.digest("SHA-256",new TextEncoder().encode(value));
  return [...new Uint8Array(bytes)].map(b=>b.toString(16).padStart(2,"0")).join("");
}
export async function postConfirmedReceivingPayment(db,{ownerId,agentId,invoiceId,now=new Date().toISOString()}={}){
  if(typeof ownerId!=="string"||typeof agentId!=="string"||typeof invoiceId!=="string")return {ok:false,reason:"invalid_receipt_identity"};
  const invoice=await db.prepare("SELECT invoice_id,owner_id,agent_id,wallet_id,amount_minor,network,chain_id,asset_code,token_contract,status FROM financial_receiving_invoices WHERE invoice_id=? AND owner_id=? AND agent_id=?")
    .bind(invoiceId,ownerId,agentId).first();
  if(!invoice)return {ok:false,reason:"invoice_not_found"};
  if(invoice.status!=="confirmed"||invoice.network!==ASSET.network||invoice.chain_id!==ASSET.chain_id||
    invoice.asset_code!==ASSET.asset_code||String(invoice.token_contract).toLowerCase()!==ASSET.token_contract)
    return {ok:false,reason:"confirmed_supported_invoice_required"};
  const evidence=await db.prepare("SELECT observation_id,tx_hash,block_number,block_hash,amount_minor,status FROM financial_receiving_payment_observations WHERE invoice_id=? AND owner_id=? AND agent_id=?")
    .bind(invoiceId,ownerId,agentId).first();
  if(!evidence||evidence.status!=="confirmed"||evidence.amount_minor!==invoice.amount_minor)
    return {ok:false,reason:"exact_confirmed_chain_evidence_required"};
  const normalized={owner_id:ownerId,agent_id:agentId,invoice_id:invoiceId,tx_hash:evidence.tx_hash,
    block_number:evidence.block_number,block_hash:evidence.block_hash,amount_minor:evidence.amount_minor,...ASSET};
  const payloadHash=await hash(canonical(normalized));
  const idempotencyKey="receiving-payment:"+invoiceId;
  const existing=await db.prepare("SELECT transaction_id,payload_hash FROM financial_asset_journal_transactions WHERE idempotency_key=?")
    .bind(idempotencyKey).first();
  if(existing)return existing.payload_hash===payloadHash
    ? {ok:true,idempotent:true,transaction_id:existing.transaction_id,amount_minor:evidence.amount_minor,asset:"USDC",status:"pending_wallet_control"}
    : {ok:false,reason:"receipt_journal_idempotency_conflict"};
  const pendingCustodyId=crypto.randomUUID(),pendingRevenueId=crypto.randomUUID();
  await db.batch([
    db.prepare("INSERT OR IGNORE INTO financial_asset_accounts(account_id,owner_id,agent_id,wallet_id,account_type,network,chain_id,asset_code,token_contract,token_decimals,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,'active',?,?)")
      .bind(pendingCustodyId,ownerId,agentId,invoice.wallet_id,"agent_pending_custody",ASSET.network,ASSET.chain_id,ASSET.asset_code,ASSET.token_contract,ASSET.token_decimals,now,now),
    db.prepare("INSERT OR IGNORE INTO financial_asset_accounts(account_id,owner_id,agent_id,wallet_id,account_type,network,chain_id,asset_code,token_contract,token_decimals,status,created_at,updated_at) VALUES(?,?,?,NULL,'agent_pending_revenue',?,?,?,?,?,'active',?,?)")
      .bind(pendingRevenueId,ownerId,agentId,ASSET.network,ASSET.chain_id,ASSET.asset_code,ASSET.token_contract,ASSET.token_decimals,now,now)
  ]);
  const accounts=await db.prepare("SELECT account_id,account_type,status FROM financial_asset_accounts WHERE owner_id=? AND agent_id=? AND ((wallet_id=? AND account_type='agent_pending_custody') OR (wallet_id IS NULL AND account_type='agent_pending_revenue'))")
    .bind(ownerId,agentId,invoice.wallet_id).all();
  const rows=accounts.results||[];
  const custody=rows.find(x=>x.account_type==="agent_pending_custody"&&x.status==="active");
  const revenue=rows.find(x=>x.account_type==="agent_pending_revenue"&&x.status==="active");
  if(!custody||!revenue)return {ok:false,reason:"pending_asset_accounts_unavailable"};
  const transactionId=crypto.randomUUID(),eventId=crypto.randomUUID();
  const statements=[
    db.prepare("INSERT INTO financial_asset_journal_transactions(transaction_id,owner_id,idempotency_key,payload_hash,source_type,source_reference,network,chain_id,asset_code,token_contract,token_decimals,status,description,created_at) VALUES(?,?,?,?,? ,?,?,?,?,?,?,'posted',?,?)")
      .bind(transactionId,ownerId,idempotencyKey,payloadHash,"receiving_payment",invoiceId,ASSET.network,ASSET.chain_id,ASSET.asset_code,ASSET.token_contract,ASSET.token_decimals,"Confirmed Base USDC receipt awaiting wallet-control verification",now),
    db.prepare("INSERT INTO financial_asset_journal_postings(transaction_id,line_number,account_id,direction,amount_minor,network,chain_id,asset_code,token_contract,token_decimals,created_at) VALUES(?,1,?,'debit',?,?,?,?,?,?,?)")
      .bind(transactionId,custody.account_id,evidence.amount_minor,ASSET.network,ASSET.chain_id,ASSET.asset_code,ASSET.token_contract,ASSET.token_decimals,now),
    db.prepare("INSERT INTO financial_asset_journal_postings(transaction_id,line_number,account_id,direction,amount_minor,network,chain_id,asset_code,token_contract,token_decimals,created_at) VALUES(?,2,?,'credit',?,?,?,?,?,?,?)")
      .bind(transactionId,revenue.account_id,evidence.amount_minor,ASSET.network,ASSET.chain_id,ASSET.asset_code,ASSET.token_contract,ASSET.token_decimals,now),
    db.prepare("INSERT INTO financial_audit_events(event_id,owner_id,actor_id,event_type,target_type,target_id,request_id,details_json,created_at) VALUES(?,?,?,?,?,?,?,?,?)")
      .bind(eventId,ownerId,ownerId,"financial.asset_receipt_journaled","receiving_invoice",invoiceId,evidence.tx_hash,
        JSON.stringify({agent_id:agentId,amount_minor:evidence.amount_minor,asset:"USDC",network:ASSET.network,spendable:false}),now)
  ];
  try{await db.batch(statements);}
  catch(error){
    const raced=await db.prepare("SELECT transaction_id,payload_hash FROM financial_asset_journal_transactions WHERE idempotency_key=?").bind(idempotencyKey).first();
    if(raced&&raced.payload_hash===payloadHash)return {ok:true,idempotent:true,transaction_id:raced.transaction_id,amount_minor:evidence.amount_minor,asset:"USDC",status:"pending_wallet_control"};
    if(raced)return {ok:false,reason:"receipt_journal_idempotency_conflict"};
    throw error;
  }
  return {ok:true,idempotent:false,transaction_id:transactionId,amount_minor:evidence.amount_minor,asset:"USDC",status:"pending_wallet_control",
    notice:"Receipt is recorded in the asset ledger but is not spendable until control of the receiving wallet is verified."};
}

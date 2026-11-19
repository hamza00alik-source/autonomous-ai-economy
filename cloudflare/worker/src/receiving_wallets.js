const USDC_BASE = Object.freeze({
  network: "base-mainnet",
  chainId: 8453,
  assetCode: "USDC",
  tokenContract: "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
  decimals: 6,
});
const ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{2,79}$/;
const ADDRESS = /^0x[a-fA-F0-9]{40}$/;

function sorted(value) {
  if (Array.isArray(value)) return value.map(sorted);
  if (value && typeof value === "object") return Object.keys(value).sort().reduce((out,key)=>{out[key]=sorted(value[key]);return out;},{});
  return value;
}
export function canonicalReceivingWalletPayload(value) { return JSON.stringify(sorted(value)); }
function decode64url(value) {
  if (typeof value !== "string" || !/^[A-Za-z0-9_-]+$/.test(value)) return null;
  try {
    const padded=value.replace(/-/g,"+").replace(/_/g,"/")+"=".repeat((4-value.length%4)%4);
    return Uint8Array.from(atob(padded),c=>c.charCodeAt(0));
  } catch { return null; }
}
async function sha256(value) {
  const digest=await crypto.subtle.digest("SHA-256",new TextEncoder().encode(value));
  return [...new Uint8Array(digest)].map(x=>x.toString(16).padStart(2,"0")).join("");
}
export function parseUsdcAmount(value) {
  if (typeof value !== "string" || !/^(?:0|[1-9]\d{0,8})(?:\.\d{1,6})?$/.test(value)) return null;
  const [whole,fraction=""]=value.split(".");
  const minor=Number(whole)*1_000_000+Number((fraction+"000000").slice(0,6));
  return Number.isSafeInteger(minor)&&minor>0?minor:null;
}
export function buildBaseUsdcPaymentUri(address, amountMinor) {
  if (!ADDRESS.test(address) || !Number.isSafeInteger(amountMinor) || amountMinor<=0) return null;
  return `ethereum:${USDC_BASE.tokenContract}@${USDC_BASE.chainId}/transfer?address=${address}&uint256=${amountMinor}`;
}
export async function registerAgentReceivingWallet(db,{ownerId,agentId,address,signatureBase64Url,now=new Date().toISOString()}={}) {
  if(!ID.test(ownerId||"")||!ID.test(agentId||"")||!ADDRESS.test(address||"")) return {ok:false,reason:"invalid_wallet_registration_fields"};
  const owner=await db.prepare("SELECT participant_id,participant_type,status,public_key_jwk,key_fingerprint FROM financial_participants WHERE participant_id=?")
    .bind(ownerId).first();
  const agent=await db.prepare("SELECT participant_id,participant_type,status,owner_id,operator_id FROM financial_participants WHERE participant_id=?")
    .bind(agentId).first();
  if(!owner||owner.participant_type!=="owner"||owner.status!=="active"||!owner.public_key_jwk||!owner.key_fingerprint) return {ok:false,reason:"active_owner_signing_key_required"};
  if(!agent||agent.participant_type!=="agent"||agent.status!=="active"||agent.owner_id!==ownerId) return {ok:false,reason:"active_owned_agent_required"};
  const payload={version:1,owner_id:ownerId,agent_id:agentId,network:USDC_BASE.network,chain_id:USDC_BASE.chainId,
    asset_code:USDC_BASE.assetCode,token_contract:USDC_BASE.tokenContract.toLowerCase(),token_decimals:USDC_BASE.decimals,
    receiving_address:address.toLowerCase()};
  const canonical=canonicalReceivingWalletPayload(payload);
  const signature=decode64url(signatureBase64Url);
  if(!signature||signature.length!==64) return {ok:false,reason:"invalid_owner_signature"};
  let key;
  try { key=await crypto.subtle.importKey("jwk",JSON.parse(owner.public_key_jwk),{name:"Ed25519"},false,["verify"]); }
  catch { return {ok:false,reason:"invalid_owner_public_key"}; }
  const valid=await crypto.subtle.verify({name:"Ed25519"},key,signature,new TextEncoder().encode(canonical));
  if(!valid) return {ok:false,reason:"invalid_owner_signature"};
  const payloadHash=await sha256(canonical);
  const existing=await db.prepare("SELECT wallet_id,receiving_address,registration_payload_hash,status FROM financial_agent_receiving_wallets WHERE owner_id=? AND agent_id=? AND network=? AND asset_code=? AND status='active'")
    .bind(ownerId,agentId,USDC_BASE.network,USDC_BASE.assetCode).first();
  if(existing) return existing.registration_payload_hash===payloadHash
    ? {ok:true,idempotent:true,wallet_id:existing.wallet_id,address:existing.receiving_address,network:USDC_BASE.network,asset:USDC_BASE.assetCode}
    : {ok:false,reason:"active_receiving_wallet_already_exists_revoke_before_replacement"};
  const walletId=crypto.randomUUID();
  const eventId=crypto.randomUUID();
  try {
    await db.batch([
      db.prepare("INSERT INTO financial_agent_receiving_wallets(wallet_id,owner_id,agent_id,network,chain_id,asset_code,token_contract,token_decimals,receiving_address,status,signer_key_fingerprint,registration_payload_hash,registration_signature,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,'active',?,?,?,?,?)")
        .bind(walletId,ownerId,agentId,USDC_BASE.network,USDC_BASE.chainId,USDC_BASE.assetCode,USDC_BASE.tokenContract.toLowerCase(),USDC_BASE.decimals,address.toLowerCase(),owner.key_fingerprint,payloadHash,signatureBase64Url,now,now),
      db.prepare("INSERT INTO financial_audit_events(event_id,owner_id,actor_id,event_type,target_type,target_id,request_id,details_json,created_at) VALUES(?,?,?,?,?,?,?,?,?)")
        .bind(eventId,ownerId,ownerId,"financial.receiving_wallet_registered","agent_receiving_wallet",walletId,payloadHash,
          JSON.stringify({agent_id:agentId,network:USDC_BASE.network,asset:USDC_BASE.assetCode,address:address.toLowerCase()}),now)
    ]);
    return {ok:true,idempotent:false,wallet_id:walletId,address:address.toLowerCase(),network:USDC_BASE.network,asset:USDC_BASE.assetCode};
  } catch(error) {
    const raced=await db.prepare("SELECT wallet_id,receiving_address,registration_payload_hash FROM financial_agent_receiving_wallets WHERE owner_id=? AND agent_id=? AND network=? AND asset_code=? AND status='active'")
      .bind(ownerId,agentId,USDC_BASE.network,USDC_BASE.assetCode).first();
    if(raced&&raced.registration_payload_hash===payloadHash) return {ok:true,idempotent:true,wallet_id:raced.wallet_id,address:raced.receiving_address,network:USDC_BASE.network,asset:USDC_BASE.assetCode};
    throw error;
  }
}
export async function createAgentReceivingInvoice(db,{ownerId,agentId,orderId,amount,description,expiresInMinutes=60,now=new Date().toISOString()}={}) {
  if(!ID.test(ownerId||"")||!ID.test(agentId||"")||!ID.test(orderId||"")) return {ok:false,reason:"invalid_invoice_identity"};
  const amountMinor=parseUsdcAmount(amount);
  if(!amountMinor) return {ok:false,reason:"invalid_usdc_amount"};
  if(typeof description!=="string"||!description.trim()||description.length>200) return {ok:false,reason:"invalid_description"};
  if(!Number.isInteger(expiresInMinutes)||expiresInMinutes<5||expiresInMinutes>1440) return {ok:false,reason:"invalid_expiry"};
  const wallet=await db.prepare("SELECT wallet_id,receiving_address,network,chain_id,asset_code,token_contract,token_decimals FROM financial_agent_receiving_wallets WHERE owner_id=? AND agent_id=? AND status='active' AND network=? AND asset_code=?")
    .bind(ownerId,agentId,USDC_BASE.network,USDC_BASE.assetCode).first();
  if(!wallet) return {ok:false,reason:"agent_receiving_wallet_not_configured"};
  const existing=await db.prepare("SELECT invoice_id,amount_minor,payment_uri,status,expires_at FROM financial_receiving_invoices WHERE owner_id=? AND agent_id=? AND order_id=?")
    .bind(ownerId,agentId,orderId).first();
  if(existing) return existing.amount_minor===amountMinor
    ? {ok:true,idempotent:true,...existing,asset:USDC_BASE.assetCode,network:USDC_BASE.network}
    : {ok:false,reason:"order_id_reused_with_different_amount"};
  const invoiceId=crypto.randomUUID();
  const expiresAt=new Date(Date.parse(now)+expiresInMinutes*60_000).toISOString();
  const paymentUri=buildBaseUsdcPaymentUri(wallet.receiving_address,amountMinor);
  try {
    await db.prepare("INSERT INTO financial_receiving_invoices(invoice_id,owner_id,agent_id,wallet_id,order_id,amount_minor,asset_code,network,chain_id,token_contract,receiving_address,payment_uri,description,status,expires_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,'awaiting_payment',?,?,?)")
      .bind(invoiceId,ownerId,agentId,wallet.wallet_id,orderId,amountMinor,USDC_BASE.assetCode,USDC_BASE.network,wallet.chain_id,wallet.token_contract,wallet.receiving_address,paymentUri,description.trim(),expiresAt,now,now).run();
    return {ok:true,idempotent:false,invoice_id:invoiceId,order_id:orderId,amount,amount_minor:amountMinor,asset:USDC_BASE.assetCode,
      network:USDC_BASE.network,chain_id:wallet.chain_id,token_contract:wallet.token_contract,
      receiving_address:wallet.receiving_address,payment_uri:paymentUri,status:"awaiting_payment",expires_at:expiresAt,
      notice:"Payment is not confirmed by invoice creation. Funds are not credited until independent on-chain settlement verification is implemented."};
  } catch(error) {
    const raced=await db.prepare("SELECT invoice_id,amount_minor,payment_uri,status,expires_at FROM financial_receiving_invoices WHERE owner_id=? AND agent_id=? AND order_id=?")
      .bind(ownerId,agentId,orderId).first();
    if(raced&&raced.amount_minor===amountMinor) return {ok:true,idempotent:true,...raced,asset:USDC_BASE.assetCode,network:USDC_BASE.network};
    throw error;
  }
}

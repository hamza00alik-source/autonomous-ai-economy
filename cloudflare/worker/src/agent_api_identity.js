const ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{2,79}$/;
const B64URL = /^[A-Za-z0-9_-]+$/;
const encoder = new TextEncoder();

function sorted(value) {
  if (Array.isArray(value)) return value.map(sorted);
  if (value && typeof value === "object") return Object.keys(value).sort().reduce((out,key)=>{out[key]=sorted(value[key]);return out;},{});
  return value;
}
export function canonicalAgentKeyPayload(value) { return JSON.stringify(sorted(value)); }
function decode64(value) {
  if (typeof value !== "string" || !B64URL.test(value)) return null;
  try { return Uint8Array.from(atob(value.replace(/-/g,"+").replace(/_/g,"/")+"=".repeat((4-value.length%4)%4)),c=>c.charCodeAt(0)); }
  catch { return null; }
}
function encodeHex(bytes) { return [...new Uint8Array(bytes)].map(x=>x.toString(16).padStart(2,"0")).join(""); }
async function hash(value) { return encodeHex(await crypto.subtle.digest("SHA-256",typeof value==="string"?encoder.encode(value):value)); }
async function importPublic(jwk) {
  if (!jwk || jwk.kty!=="OKP" || jwk.crv!=="Ed25519" || typeof jwk.x!=="string" || jwk.d!==undefined) return null;
  try { return await crypto.subtle.importKey("jwk",jwk,{name:"Ed25519"},false,["verify"]); }
  catch { return null; }
}
async function verify(key, signature, message) {
  try { return await crypto.subtle.verify({name:"Ed25519"},key,signature,encoder.encode(message)); }
  catch { return false; }
}
export async function registerAgentApiKey(db,{ownerId,agentId,publicKeyJwk,ownerSignature,proofSignature,now=new Date().toISOString()}={}) {
  if(!ID.test(ownerId||"")||!ID.test(agentId||"")) return {ok:false,reason:"invalid_identity"};
  const agent=await db.prepare("SELECT a.status,a.owner_id,a.participant_type,o.status AS operator_status FROM financial_participants a JOIN financial_participants o ON o.participant_id=a.operator_id WHERE a.participant_id=?")
    .bind(agentId).first();
  const owner=await db.prepare("SELECT status,participant_type,public_key_jwk FROM financial_participants WHERE participant_id=?").bind(ownerId).first();
  if(!agent||agent.status!=="active"||agent.owner_id!==ownerId||agent.participant_type!=="agent"||agent.operator_status!=="active"||
     !owner||owner.status!=="active"||owner.participant_type!=="owner"||!owner.public_key_jwk) return {ok:false,reason:"active_owned_agent_and_owner_key_required"};
  const agentKey=await importPublic(publicKeyJwk);
  if(!agentKey) return {ok:false,reason:"invalid_agent_public_key"};
  const canonicalJwk=JSON.stringify({crv:"Ed25519",kty:"OKP",x:publicKeyJwk.x});
  const payload={version:1,owner_id:ownerId,agent_id:agentId,public_key_jwk:JSON.parse(canonicalJwk)};
  const canonical=canonicalAgentKeyPayload(payload);
  const ownerSig=decode64(ownerSignature), proofSig=decode64(proofSignature);
  if(!ownerSig||ownerSig.length!==64||!proofSig||proofSig.length!==64) return {ok:false,reason:"invalid_registration_signatures"};
  let ownerKey;
  try { ownerKey=await crypto.subtle.importKey("jwk",JSON.parse(owner.public_key_jwk),{name:"Ed25519"},false,["verify"]); }
  catch { return {ok:false,reason:"invalid_owner_public_key"}; }
  if(!await verify(ownerKey,ownerSig,canonical)) return {ok:false,reason:"invalid_owner_authorization"};
  const fingerprint=await hash(canonicalJwk);
  if(!await verify(agentKey,proofSig,"AAE-AGENT-KEY-PROOF:v1:"+fingerprint)) return {ok:false,reason:"agent_proof_of_possession_failed"};
  const existing=await db.prepare("SELECT key_id,key_fingerprint,status FROM financial_agent_api_keys WHERE owner_id=? AND agent_id=? AND key_fingerprint=?")
    .bind(ownerId,agentId,fingerprint).first();
  if(existing) return existing.status==="active"?{ok:true,idempotent:true,key_id:existing.key_id,key_fingerprint:fingerprint}:{ok:false,reason:"key_fingerprint_previously_revoked"};
  const active=await db.prepare("SELECT key_id FROM financial_agent_api_keys WHERE owner_id=? AND agent_id=? AND status='active'").bind(ownerId,agentId).first();
  if(active) return {ok:false,reason:"active_agent_api_key_exists_revoke_before_rotation"};
  const keyId=crypto.randomUUID();
  await db.prepare("INSERT INTO financial_agent_api_keys(key_id,owner_id,agent_id,public_key_jwk,key_fingerprint,status,created_at) VALUES(?,?,?,?,?,'active',?)")
    .bind(keyId,ownerId,agentId,canonicalJwk,fingerprint,now).run();
  return {ok:true,idempotent:false,key_id:keyId,key_fingerprint:fingerprint};
}
export async function authenticateAgentRequest(db,{agentId,method,path,body,timestamp,nonce,signature,keyFingerprint,nowMs=Date.now()}={}) {
  if(!ID.test(agentId||"")||!Number.isSafeInteger(Number(timestamp))||!B64URL.test(nonce||"")||nonce.length<16||nonce.length>96) return {ok:false,reason:"invalid_agent_auth_headers"};
  const requestTime=Number(timestamp);
  if(Math.abs(nowMs-requestTime)>300_000) return {ok:false,reason:"agent_request_timestamp_outside_window"};
  const key=await db.prepare("SELECT key_id,owner_id,agent_id,public_key_jwk FROM financial_agent_api_keys WHERE agent_id=? AND key_fingerprint=? AND status='active'")
    .bind(agentId,keyFingerprint).first();
  if(!key) return {ok:false,reason:"unknown_or_revoked_agent_key"};
  const bodyHash=await hash(body);
  const canonical=[String(method).toUpperCase(),path,String(requestTime),nonce,bodyHash].join("\n");
  let publicKey;
  try { publicKey=await crypto.subtle.importKey("jwk",JSON.parse(key.public_key_jwk),{name:"Ed25519"},false,["verify"]); }
  catch { return {ok:false,reason:"invalid_registered_agent_key"}; }
  const decoded=decode64(signature);
  if(!decoded||decoded.length!==64||!await verify(publicKey,decoded,canonical)) return {ok:false,reason:"invalid_agent_request_signature"};
  try {
    await db.prepare("DELETE FROM financial_agent_api_nonces WHERE request_timestamp < ?").bind(nowMs-300_000).run();
    await db.prepare("INSERT INTO financial_agent_api_nonces(key_id,nonce,request_timestamp,created_at) VALUES(?,?,?,?)")
      .bind(key.key_id,nonce,requestTime,new Date(nowMs).toISOString()).run();
  } catch { return {ok:false,reason:"agent_request_replay_detected"}; }
  return {ok:true,ownerId:key.owner_id,agentId:key.agent_id,keyId:key.key_id};
}

export async function revokeAgentApiKey(db,{ownerId,agentId,keyId,ownerSignature,now=new Date().toISOString()}={}) {
  if(!ID.test(ownerId||"")||!ID.test(agentId||"")||typeof keyId!=="string"||keyId.length>64) return {ok:false,reason:"invalid_revocation_identity"};
  const owner=await db.prepare("SELECT status,participant_type,public_key_jwk FROM financial_participants WHERE participant_id=?").bind(ownerId).first();
  const key=await db.prepare("SELECT key_id,status FROM financial_agent_api_keys WHERE key_id=? AND owner_id=? AND agent_id=?").bind(keyId,ownerId,agentId).first();
  if(!owner||owner.status!=="active"||owner.participant_type!=="owner"||!owner.public_key_jwk||!key) return {ok:false,reason:"owner_or_agent_key_not_found"};
  if(key.status==="revoked") return {ok:true,idempotent:true,key_id:keyId,status:"revoked"};
  const payload=canonicalAgentKeyPayload({version:1,action:"revoke_agent_api_key",owner_id:ownerId,agent_id:agentId,key_id:keyId});
  const signature=decode64(ownerSignature);
  if(!signature||signature.length!==64) return {ok:false,reason:"invalid_owner_revocation_signature"};
  let ownerKey;
  try { ownerKey=await crypto.subtle.importKey("jwk",JSON.parse(owner.public_key_jwk),{name:"Ed25519"},false,["verify"]); }
  catch { return {ok:false,reason:"invalid_owner_public_key"}; }
  if(!await verify(ownerKey,signature,payload)) return {ok:false,reason:"invalid_owner_revocation_signature"};
  await db.prepare("UPDATE financial_agent_api_keys SET status='revoked',revoked_at=? WHERE key_id=? AND owner_id=? AND agent_id=? AND status='active'")
    .bind(now,keyId,ownerId,agentId).run();
  return {ok:true,idempotent:false,key_id:keyId,status:"revoked"};
}

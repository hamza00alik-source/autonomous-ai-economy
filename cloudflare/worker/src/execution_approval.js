const encoder = new TextEncoder();
const ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{2,79}$/;
const IDEMPOTENCY = /^[A-Za-z0-9._:-]{8,128}$/;
const SPEC = Object.freeze({ kind: "moba_objective_props_v1" });

function sorted(value) {
  if (Array.isArray(value)) return value.map(sorted);
  if (value && typeof value === "object") return Object.keys(value).sort().reduce((out,key)=>{out[key]=sorted(value[key]);return out;},{});
  return value;
}
export function canonicalExecutionApproval(value) { return JSON.stringify(sorted(value)); }
function decode64(value) {
  if (typeof value !== "string" || !/^[A-Za-z0-9_-]+$/.test(value)) return null;
  try { return Uint8Array.from(atob(value.replace(/-/g,"+").replace(/_/g,"/")+"=".repeat((4-value.length%4)%4)),c=>c.charCodeAt(0)); }
  catch { return null; }
}
async function importOwnerKey(jwk) {
  if (!jwk || jwk.kty !== "OKP" || jwk.crv !== "Ed25519" ||
      typeof jwk.x !== "string" || "d" in jwk) return null;
  try { return await crypto.subtle.importKey("jwk",jwk,{name:"Ed25519"},false,["verify"]); }
  catch { return null; }
}
export async function createExecutionApprovalChallenge(db,{ownerId,idempotencyKey,nowMs=Date.now()}={}) {
  if (!ID.test(ownerId||"") || !IDEMPOTENCY.test(idempotencyKey||"")) return {ok:false,reason:"invalid_approval_request"};
  const owner=await db.prepare("SELECT participant_id,public_key_jwk FROM financial_participants WHERE participant_id=? AND participant_type='owner' AND status='active'")
    .bind(ownerId).first();
  if (!owner?.public_key_jwk) return {ok:false,reason:"active_owner_signing_key_required"};
  let jwk;
  try { jwk=JSON.parse(owner.public_key_jwk); } catch { return {ok:false,reason:"owner_signing_key_invalid"}; }
  if (!await importOwnerKey(jwk)) return {ok:false,reason:"owner_signing_key_invalid"};
  const issuedAt=Math.floor(nowMs/1000);
  const payload={
    version:1, owner_id:ownerId, action:"execute_internal_product",
    agent_id:"game-asset-builder", execution_spec:SPEC,
    idempotency_key:idempotencyKey, nonce:crypto.randomUUID(),
    issued_at:issuedAt, expires_at:issuedAt+300
  };
  return {ok:true,payload,canonical_payload:canonicalExecutionApproval(payload),public_key_jwk:{kty:"OKP",crv:"Ed25519",x:jwk.x}};
}
export async function verifyAndConsumeExecutionApproval(db,{ownerId,idempotencyKey,approval,nowMs=Date.now()}={}) {
  if (!ID.test(ownerId||"") || !IDEMPOTENCY.test(idempotencyKey||"") ||
      !approval || typeof approval!=="object" || Array.isArray(approval) ||
      Object.keys(approval).sort().join(",")!=="canonical_payload,signature") {
    return {ok:false,reason:"invalid_owner_approval_envelope"};
  }
  let payload;
  try { payload=JSON.parse(approval.canonical_payload); } catch { return {ok:false,reason:"invalid_owner_approval_payload"}; }
  if (canonicalExecutionApproval(payload)!==approval.canonical_payload ||
      payload.version!==1 || payload.owner_id!==ownerId ||
      payload.action!=="execute_internal_product" || payload.agent_id!=="game-asset-builder" ||
      canonicalExecutionApproval(payload.execution_spec)!==canonicalExecutionApproval(SPEC) ||
      payload.idempotency_key!==idempotencyKey ||
      typeof payload.nonce!=="string" || !/^[0-9a-f-]{36}$/i.test(payload.nonce) ||
      !Number.isSafeInteger(payload.issued_at) || !Number.isSafeInteger(payload.expires_at) ||
      payload.expires_at-payload.issued_at!==300) return {ok:false,reason:"owner_approval_scope_mismatch"};
  const now=Math.floor(nowMs/1000);
  if (payload.issued_at>now+30 || payload.expires_at<now || payload.issued_at<now-300) return {ok:false,reason:"owner_approval_expired"};
  const owner=await db.prepare("SELECT public_key_jwk FROM financial_participants WHERE participant_id=? AND participant_type='owner' AND status='active'")
    .bind(ownerId).first();
  let jwk;
  try { jwk=JSON.parse(owner?.public_key_jwk||"null"); } catch { return {ok:false,reason:"owner_signing_key_invalid"}; }
  const key=await importOwnerKey(jwk);
  const signature=decode64(approval.signature);
  if (!key || !signature || signature.length!==64) return {ok:false,reason:"owner_approval_signature_invalid"};
  let valid=false;
  try { valid=await crypto.subtle.verify({name:"Ed25519"},key,signature,encoder.encode(approval.canonical_payload)); } catch {}
  if (!valid) return {ok:false,reason:"owner_approval_signature_invalid"};
  try {
    await db.prepare("INSERT INTO internal_execution_approval_nonces(owner_id,nonce,idempotency_key,expires_at,consumed_at) VALUES(?,?,?,?,?)")
      .bind(ownerId,payload.nonce,idempotencyKey,new Date(nowMs).toISOString(),new Date(nowMs).toISOString()).run();
  } catch { return {ok:false,reason:"owner_approval_replayed"}; }
  return {ok:true,payload};
}

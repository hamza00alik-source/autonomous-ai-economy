const POLICY_KEYS = ["agent_id","allowed_destinations","currency","daily_spend_limit_minor","owner_id","per_transaction_limit_minor","policy_id","version"];
function sortedJson(value) {
  if (Array.isArray(value)) return value.map(sortedJson);
  if (value && typeof value === "object") return Object.keys(value).sort().reduce((out,key)=>{out[key]=sortedJson(value[key]);return out;},{});
  return value;
}
export function canonicalizeFinancialPolicy(policy) { return JSON.stringify(sortedJson(policy)); }
export function validateFinancialPolicy(policy) {
  if (!policy || typeof policy !== "object" || Array.isArray(policy)) return "invalid_policy";
  const keys=Object.keys(policy).sort();
  if(keys.length!==POLICY_KEYS.length||keys.some((key,i)=>key!==POLICY_KEYS[i])) return "policy_schema_mismatch";
  if(typeof policy.policy_id!=="string"||!/^[A-Za-z0-9][A-Za-z0-9._:-]{2,79}$/.test(policy.policy_id)) return "invalid_policy_id";
  if(!Number.isSafeInteger(policy.version)||policy.version<1) return "invalid_policy_version";
  for(const key of ["owner_id","agent_id"]) if(typeof policy[key]!=="string"||!/^[A-Za-z0-9][A-Za-z0-9._:-]{2,79}$/.test(policy[key])) return "invalid_participant_id";
  if(!/^[A-Z]{3}$/.test(policy.currency)) return "invalid_currency";
  for(const key of ["per_transaction_limit_minor","daily_spend_limit_minor"]) if(!Number.isSafeInteger(policy[key])||policy[key]<=0) return "invalid_spend_limit";
  if(policy.per_transaction_limit_minor>policy.daily_spend_limit_minor) return "transaction_limit_exceeds_daily_limit";
  const destinations=policy.allowed_destinations;
  if(!Array.isArray(destinations)||destinations.length<1||destinations.length>50) return "invalid_destination_allowlist";
  if(destinations.some(value=>typeof value!=="string"||!value.trim()||value.length>256||value.trim()!==value||value.includes("*"))) return "invalid_destination";
  if(new Set(destinations).size!==destinations.length) return "duplicate_destination";
  return null;
}
function decodeBase64Url(value) {
  if(typeof value!=="string"||!/^[A-Za-z0-9_-]+$/.test(value)) return null;
  const padded=value.replace(/-/g,"+").replace(/_/g,"/")+"=".repeat((4-value.length%4)%4);
  try { return Uint8Array.from(atob(padded),c=>c.charCodeAt(0)); } catch { return null; }
}
async function sha256Hex(value) {
  const digest=await crypto.subtle.digest("SHA-256",new TextEncoder().encode(value));
  return [...new Uint8Array(digest)].map(byte=>byte.toString(16).padStart(2,"0")).join("");
}
export async function financialPublicKeyFingerprint(jwk) {
  if(!jwk||typeof jwk!=="object"||jwk.kty!=="OKP"||jwk.crv!=="Ed25519"||typeof jwk.x!=="string"||"d" in jwk) return null;
  return sha256Hex(JSON.stringify({crv:jwk.crv,kty:jwk.kty,x:jwk.x}));
}
export async function verifyOwnerSignedFinancialPolicy({policy,canonicalPayload,signatureBase64Url,signerKeyFingerprint,signerJwk,owner,signer,agent}) {
  const invalid=validateFinancialPolicy(policy);
  if(invalid) return {ok:false,reason:invalid};
  if(canonicalPayload!==canonicalizeFinancialPolicy(policy)) return {ok:false,reason:"noncanonical_policy_payload"};
  if(!owner||owner.participant_type!=="owner"||owner.status!=="active"||owner.participant_id!==policy.owner_id) return {ok:false,reason:"owner_not_active"};
  if(!signer||signer.participant_type!=="operator"||signer.status!=="active"||signer.owner_id!==owner.participant_id||signer.participant_id!==agent?.operator_id) return {ok:false,reason:"signer_not_authorized_operator"};
  if(!agent||agent.participant_type!=="agent"||agent.status!=="active"||agent.owner_id!==owner.participant_id||agent.participant_id!==policy.agent_id) return {ok:false,reason:"agent_not_active_or_owned"};
  if(!signerJwk||signer.key_fingerprint!==signerKeyFingerprint) return {ok:false,reason:"signer_key_fingerprint_mismatch"};
  const fingerprint=await financialPublicKeyFingerprint(signerJwk);
  if(!fingerprint||fingerprint!==signerKeyFingerprint) return {ok:false,reason:"signer_key_invalid"};
  const signature=decodeBase64Url(signatureBase64Url);
  if(!signature||signature.length!==64) return {ok:false,reason:"invalid_signature_encoding"};
  try {
    const key=await crypto.subtle.importKey("jwk",{crv:signerJwk.crv,ext:true,key_ops:["verify"],kty:signerJwk.kty,x:signerJwk.x},{name:"Ed25519"},false,["verify"]);
    const ok=await crypto.subtle.verify({name:"Ed25519"},key,signature,new TextEncoder().encode(canonicalPayload));
    return ok?{ok:true,policy}:{ok:false,reason:"invalid_owner_signature"};
  } catch { return {ok:false,reason:"signature_verification_failed"}; }
}
export async function loadActiveCloudFinancialPolicy(db,agentId) {
  if(typeof agentId!=="string"||!/^[A-Za-z0-9][A-Za-z0-9._:-]{2,79}$/.test(agentId)) return {ok:false,reason:"invalid_agent_id"};
  const row=await db.prepare(`
    SELECT p.policy_id,p.version,p.owner_id,p.agent_id,p.signer_id,p.currency,p.per_transaction_limit_minor,p.daily_spend_limit_minor,p.allowed_destinations_json,p.canonical_payload,p.signature_base64url,p.signer_key_fingerprint,p.status,
      o.participant_id AS owner_participant_id,o.participant_type AS owner_type,o.status AS owner_status,
      s.participant_id AS signer_participant_id,s.participant_type AS signer_type,s.status AS signer_status,s.owner_id AS signer_owner_id,s.public_key_jwk AS signer_public_key_jwk,s.key_fingerprint AS signer_fingerprint,
      a.participant_id AS agent_participant_id,a.participant_type AS agent_type,a.status AS agent_status,a.owner_id AS agent_owner_id,a.operator_id AS agent_operator_id
    FROM financial_policies p
    JOIN financial_participants o ON o.participant_id=p.owner_id
    JOIN financial_participants s ON s.participant_id=p.signer_id
    JOIN financial_participants a ON a.participant_id=p.agent_id
    WHERE p.agent_id=? AND p.status='active' ORDER BY p.version DESC LIMIT 1
  `).bind(agentId).first();
  if(!row) return {ok:false,reason:"active_policy_not_found"};
  let policy,signerJwk,destinations;
  try { policy=JSON.parse(row.canonical_payload); signerJwk=JSON.parse(row.signer_public_key_jwk); destinations=JSON.parse(row.allowed_destinations_json); }
  catch { return {ok:false,reason:"stored_policy_malformed"}; }
  if(JSON.stringify(sortedJson(destinations))!==JSON.stringify(sortedJson(policy.allowed_destinations))) return {ok:false,reason:"stored_destination_allowlist_mismatch"};
  if(row.policy_id!==policy.policy_id||row.version!==policy.version||row.owner_id!==policy.owner_id||row.agent_id!==policy.agent_id||row.signer_id!==row.signer_participant_id||row.currency!==policy.currency||row.per_transaction_limit_minor!==policy.per_transaction_limit_minor||row.daily_spend_limit_minor!==policy.daily_spend_limit_minor) return {ok:false,reason:"stored_policy_columns_mismatch"};
  return verifyOwnerSignedFinancialPolicy({
    policy,canonicalPayload:row.canonical_payload,signatureBase64Url:row.signature_base64url,signerKeyFingerprint:row.signer_key_fingerprint,signerJwk,
    owner:{participant_id:row.owner_participant_id,participant_type:row.owner_type,status:row.owner_status},
    signer:{participant_id:row.signer_participant_id,participant_type:row.signer_type,status:row.signer_status,owner_id:row.signer_owner_id,key_fingerprint:row.signer_fingerprint},
    agent:{participant_id:row.agent_participant_id,participant_type:row.agent_type,status:row.agent_status,owner_id:row.agent_owner_id,operator_id:row.agent_operator_id}
  });
}

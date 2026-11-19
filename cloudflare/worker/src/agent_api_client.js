const encoder=new TextEncoder();
const ID=/^[A-Za-z0-9][A-Za-z0-9._:-]{2,79}$/;
function sorted(value){
  if(Array.isArray(value))return value.map(sorted);
  if(value&&typeof value==="object")return Object.keys(value).sort().reduce((out,key)=>{out[key]=sorted(value[key]);return out;},{});
  return value;
}
export function canonicalAgentApiPayload(value){return JSON.stringify(sorted(value));}
function bytesToBase64Url(bytes){return btoa(String.fromCharCode(...new Uint8Array(bytes))).replace(/\+/g,"-").replace(/\//g,"_").replace(/=+$/g,"");}
async function sha256Hex(value){
  const digest=await crypto.subtle.digest("SHA-256",typeof value==="string"?encoder.encode(value):value);
  return [...new Uint8Array(digest)].map(byte=>byte.toString(16).padStart(2,"0")).join("");
}
export async function generateAgentApiIdentity(){
  const pair=await crypto.subtle.generateKey({name:"Ed25519"},false,["sign","verify"]);
  const exported=await crypto.subtle.exportKey("jwk",pair.publicKey);
  const publicKeyJwk={crv:"Ed25519",kty:"OKP",x:exported.x};
  const canonicalJwk=JSON.stringify(publicKeyJwk);
  const keyFingerprint=await sha256Hex(canonicalJwk);
  return {privateKey:pair.privateKey,publicKeyJwk,keyFingerprint};
}
export async function createAgentKeyEnrollment({identity,ownerPrivateKey,ownerId,agentId}={}){
  if(!identity?.privateKey||!identity.publicKeyJwk||!ownerPrivateKey||!ID.test(ownerId||"")||!ID.test(agentId||""))throw new Error("identity, owner signing key, owner ID and agent ID are required");
  const payload={version:1,owner_id:ownerId,agent_id:agentId,public_key_jwk:identity.publicKeyJwk};
  const canonical=canonicalAgentApiPayload(payload);
  const ownerSignature=await crypto.subtle.sign({name:"Ed25519"},ownerPrivateKey,encoder.encode(canonical));
  const proofSignature=await crypto.subtle.sign({name:"Ed25519"},identity.privateKey,encoder.encode("AAE-AGENT-KEY-PROOF:v1:"+identity.keyFingerprint));
  return {public_key_jwk:identity.publicKeyJwk,owner_signature:bytesToBase64Url(ownerSignature),proof_signature:bytesToBase64Url(proofSignature)};
}
export async function signAgentApiRequest({identity,method,path,body,timestamp=Date.now(),nonce}={}){
  if(!identity?.privateKey||!/^[0-9a-f]{64}$/.test(identity.keyFingerprint||"")||typeof method!=="string"||typeof path!=="string"||typeof body!=="string")throw new Error("identity, method, path and exact raw body string are required");
  const requestNonce=nonce||bytesToBase64Url(crypto.getRandomValues(new Uint8Array(24)));
  if(!Number.isSafeInteger(timestamp)||!/^[A-Za-z0-9_-]{16,96}$/.test(requestNonce))throw new Error("invalid timestamp or nonce");
  const bodyHash=await sha256Hex(body);
  const canonical=[method.toUpperCase(),path,String(timestamp),requestNonce,bodyHash].join("\n");
  const signature=await crypto.subtle.sign({name:"Ed25519"},identity.privateKey,encoder.encode(canonical));
  return {
    "X-AAE-Key":identity.keyFingerprint,
    "X-AAE-Timestamp":String(timestamp),
    "X-AAE-Nonce":requestNonce,
    "X-AAE-Signature":bytesToBase64Url(signature),
    "Content-Type":"application/json"
  };
}

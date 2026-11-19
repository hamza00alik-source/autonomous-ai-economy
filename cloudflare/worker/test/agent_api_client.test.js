import test from "node:test";
import assert from "node:assert/strict";
import { webcrypto } from "node:crypto";
import { generateAgentApiIdentity, createAgentKeyEnrollment, signAgentApiRequest } from "../src/agent_api_client.js";
import { parseUsdcAmount, buildBaseUsdcPaymentUri } from "../src/receiving_wallets.js";
if(!globalThis.crypto)Object.defineProperty(globalThis,"crypto",{value:webcrypto});
const enc=new TextEncoder();
const decode=value=>Buffer.from(value,"base64url");
const hex=bytes=>Buffer.from(bytes).toString("hex");
async function hash(value){return hex(await crypto.subtle.digest("SHA-256",enc.encode(value)));}
test("agent runtime generates non-exportable private key and owner-authorized enrollment proof",async()=>{
  const identity=await generateAgentApiIdentity();
  assert.equal(identity.privateKey.extractable,false);
  const owner=await crypto.subtle.generateKey({name:"Ed25519"},false,["sign","verify"]);
  const envelope=await createAgentKeyEnrollment({identity,ownerPrivateKey:owner.privateKey,ownerId:"owner-001",agentId:"agent-001"});
  assert.equal(envelope.public_key_jwk.d,undefined);
  const payload=JSON.stringify({agent_id:"agent-001",owner_id:"owner-001",public_key_jwk:envelope.public_key_jwk,version:1});
  const ownerOk=await crypto.subtle.verify({name:"Ed25519"},owner.publicKey,decode(envelope.owner_signature),enc.encode(payload));
  const proof=await crypto.subtle.verify({name:"Ed25519"},await crypto.subtle.importKey("jwk",envelope.public_key_jwk,{name:"Ed25519"},false,["verify"]),decode(envelope.proof_signature),enc.encode("AAE-AGENT-KEY-PROOF:v1:"+identity.keyFingerprint));
  assert.equal(ownerOk,true);assert.equal(proof,true);
});
test("agent runtime signs exact raw request body and returns API headers",async()=>{
  const identity=await generateAgentApiIdentity(), body='{"order_id":"demo-1","amount":"1.00","description":"One USDC test invoice"}';
  const timestamp=1_800_000_000_000,nonce="n".repeat(24),path="/v1/agents/agent-001/receiving-invoices";
  const headers=await signAgentApiRequest({identity,method:"POST",path,body,timestamp,nonce});
  const canonical=["POST",path,String(timestamp),nonce,await hash(body)].join("\n");
  const publicKey=await crypto.subtle.importKey("jwk",identity.publicKeyJwk,{name:"Ed25519"},false,["verify"]);
  assert.equal(headers["X-AAE-Key"],identity.keyFingerprint);
  assert.equal(await crypto.subtle.verify({name:"Ed25519"},publicKey,decode(headers["X-AAE-Signature"]),enc.encode(canonical)),true);
  assert.equal(await crypto.subtle.verify({name:"Ed25519"},publicKey,decode(headers["X-AAE-Signature"]),enc.encode(canonical.replace(await hash(body),await hash(body+" ")))),false);
});
test("one dollar invoice preview maps to exactly one million USDC base units",()=>{
  const amountMinor=parseUsdcAmount("1.00");
  assert.equal(amountMinor,1_000_000);
  const address="0x1111111111111111111111111111111111111111";
  assert.equal(buildBaseUsdcPaymentUri(address,amountMinor),"ethereum:0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913@8453/transfer?address="+address+"&uint256=1000000");
});

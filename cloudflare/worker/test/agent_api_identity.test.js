import test from "node:test";
import assert from "node:assert/strict";
import { webcrypto } from "node:crypto";
import { canonicalAgentKeyPayload, authenticateAgentRequest } from "../src/agent_api_identity.js";

if (!globalThis.crypto) Object.defineProperty(globalThis,"crypto",{value:webcrypto});
const encoder=new TextEncoder();
const b64url=bytes=>Buffer.from(bytes).toString("base64url");
const hex=bytes=>Buffer.from(bytes).toString("hex");
async function digest(value){return hex(await crypto.subtle.digest("SHA-256",encoder.encode(value)));}
function mockDb(key){
  const used=new Set();
  return {
    used,
    prepare(sql){
      let values=[];
      return {
        bind(...args){values=args;return this;},
        async first(){return sql.includes("FROM financial_agent_api_keys")?key:null;},
        async run(){
          if(sql.startsWith("DELETE FROM financial_agent_api_nonces")) return {};
          const nonce=values[1], unique=values[0]+":"+nonce;
          if(used.has(unique)) throw new Error("unique constraint");
          used.add(unique);return {};
        }
      };
    }
  };
}
test("agent key registration payload canonicalization is deterministic",()=>{
  assert.equal(canonicalAgentKeyPayload({b:2,a:1}),canonicalAgentKeyPayload({a:1,b:2}));
});
test("signed agent requests authenticate once and reject replay or body tampering",async()=>{
  const pair=await crypto.subtle.generateKey({name:"Ed25519"},true,["sign","verify"]);
  const publicJwk=await crypto.subtle.exportKey("jwk",pair.publicKey);
  const publicKeyJwk=JSON.stringify({crv:"Ed25519",kty:"OKP",x:publicJwk.x});
  const fingerprint=hex(await crypto.subtle.digest("SHA-256",encoder.encode(publicKeyJwk)));
  const key={key_id:"key-1",owner_id:"owner-1",agent_id:"agent-1",public_key_jwk:publicKeyJwk};
  const db=mockDb(key), body='{"order_id":"order-1","amount":"1.00","description":"Test"}';
  const timestamp=1_800_000_000_000, nonce="a".repeat(24), path="/v1/agents/agent-1/receiving-invoices";
  const canonical=["POST",path,String(timestamp),nonce,await digest(body)].join("\n");
  const signature=b64url(await crypto.subtle.sign({name:"Ed25519"},pair.privateKey,encoder.encode(canonical)));
  const args={agentId:"agent-1",method:"POST",path,body,timestamp:String(timestamp),nonce,signature,keyFingerprint:fingerprint,nowMs:timestamp};
  assert.deepEqual(await authenticateAgentRequest(db,args),{ok:true,ownerId:"owner-1",agentId:"agent-1",keyId:"key-1"});
  assert.deepEqual(await authenticateAgentRequest(db,args),{ok:false,reason:"agent_request_replay_detected"});
  assert.deepEqual(await authenticateAgentRequest(db,{...args,nonce:"b".repeat(24),body:body+" "}),{ok:false,reason:"invalid_agent_request_signature"});
});
test("agent requests outside the five-minute window are rejected",async()=>{
  const db=mockDb(null);
  assert.deepEqual(await authenticateAgentRequest(db,{agentId:"agent-1",method:"POST",path:"/x",body:"{}",timestamp:"1000",nonce:"c".repeat(24),signature:"x",keyFingerprint:"x",nowMs:1_000_000}),{ok:false,reason:"agent_request_timestamp_outside_window"});
});

import test from "node:test";
import assert from "node:assert/strict";
import { webcrypto } from "node:crypto";
import { canonicalExecutionApproval, createExecutionApprovalChallenge, verifyAndConsumeExecutionApproval } from "../src/execution_approval.js";
if (!globalThis.crypto) Object.defineProperty(globalThis,"crypto",{value:webcrypto});
const b64url = bytes => Buffer.from(bytes).toString("base64url");
function fakeDb(publicKeyJwk) {
  const consumed=new Set();
  return {
    consumed,
    prepare(sql) {
      let values=[];
      return {
        bind(...args){values=args;return this;},
        async first(){return {participant_id:"owner-001",public_key_jwk:JSON.stringify(publicKeyJwk)};},
        async run(){
          if(sql.startsWith("INSERT INTO internal_execution_approval_nonces")){
            const key=values[0]+":"+values[1];
            if(consumed.has(key)) throw new Error("UNIQUE constraint failed");
            consumed.add(key);
          }
          return {success:true};
        }
      };
    }
  };
}
async function fixture() {
  const pair=await crypto.subtle.generateKey({name:"Ed25519"},true,["sign","verify"]);
  const publicKeyJwk=await crypto.subtle.exportKey("jwk",pair.publicKey);
  const privateKey=pair.privateKey;
  const db=fakeDb(publicKeyJwk);
  const idempotencyKey="moba-pack-test-001";
  const challenge=await createExecutionApprovalChallenge(db,{ownerId:"owner-001",idempotencyKey});
  const signature=await crypto.subtle.sign({name:"Ed25519"},privateKey,new TextEncoder().encode(challenge.canonical_payload));
  const approval={canonical_payload:challenge.canonical_payload,signature:b64url(signature)};
  return {db,idempotencyKey,approval,challenge};
}
test("owner approval is scoped to the exact internal product and single idempotency key",async()=>{
 const f=await fixture();
 const result=await verifyAndConsumeExecutionApproval(f.db,{ownerId:"owner-001",idempotencyKey:f.idempotencyKey,approval:f.approval});
 assert.equal(result.ok,true);
 assert.equal(result.payload.action,"execute_internal_product");
 assert.equal(result.payload.execution_spec.kind,"moba_objective_props_v1");
});
test("owner approval nonce cannot be replayed",async()=>{
 const f=await fixture();
 const first=await verifyAndConsumeExecutionApproval(f.db,{ownerId:"owner-001",idempotencyKey:f.idempotencyKey,approval:f.approval});
 const second=await verifyAndConsumeExecutionApproval(f.db,{ownerId:"owner-001",idempotencyKey:f.idempotencyKey,approval:f.approval});
 assert.equal(first.ok,true);
 assert.deepEqual(second,{ok:false,reason:"owner_approval_replayed"});
});
test("owner approval rejects altered action, job scope, and malformed signature",async()=>{
 const f=await fixture();
 const payload=JSON.parse(f.approval.canonical_payload);
 payload.action="publish_product";
 const altered={canonical_payload:canonicalExecutionApproval(payload),signature:f.approval.signature};
 const result=await verifyAndConsumeExecutionApproval(f.db,{ownerId:"owner-001",idempotencyKey:f.idempotencyKey,approval:altered});
 assert.equal(result.ok,false);
 assert.equal(result.reason,"owner_approval_scope_mismatch");
 const malformed=await verifyAndConsumeExecutionApproval(f.db,{ownerId:"owner-001",idempotencyKey:f.idempotencyKey,approval:{canonical_payload:f.approval.canonical_payload,signature:"bad"}});
 assert.equal(malformed.ok,false);
});
test("owner approval challenge exposes only public key material and fixed five-minute scope",async()=>{
 const f=await fixture();
 assert.equal(f.challenge.ok,true);
 assert.equal(f.challenge.payload.expires_at-f.challenge.payload.issued_at,300);
 assert.equal("d" in f.challenge.public_key_jwk,false);
});

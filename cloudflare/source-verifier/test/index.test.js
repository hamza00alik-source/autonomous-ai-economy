import test from "node:test";
import assert from "node:assert/strict";
import verifier from "../src/index.js";
const TOKEN = "test-internal-token";
const SOURCE_URL = "https://publisher.example/article";
const EXCERPT = "This publisher describes the exact documented feature and its known limitations.";
const DRAFT = "Report. " + EXCERPT + " More context follows.";
function env(overrides = {}) {
  const calls = [];
  return { calls, INTERNAL_SERVICE_TOKEN:TOKEN, EGRESS_POLICY_ATTESTATION:"aae-source-egress-v1",
    ALLOWED_SOURCE_HOSTS:"publisher.example",
    EGRESS:{fetch:async(url,options)=>{
      calls.push({url,options});
      return new Response("<html><title>Publisher</title><p>"+EXCERPT+"</p></html>",{
        status:200,headers:{"content-type":"text/html; charset=utf-8"}});
    }}, ...overrides };
}
function request(payload={protocolVersion:1,urls:[SOURCE_URL],draft:DRAFT},token=TOKEN) {
  return new Request("https://internal/v1/verify",{method:"POST",
    headers:{"content-type":"application/json","x-aae-source-verifier-token":token},body:JSON.stringify(payload)});
}
test("refuses outbound access without VPC EGRESS binding",async()=>{
  const e=env({EGRESS:undefined}); const res=await verifier.fetch(request(),e);
  assert.equal(res.status,503); assert.match((await res.json()).error,/not configured/i);
});
test("refuses outbound access without Gateway policy attestation",async()=>{
  const e=env({EGRESS_POLICY_ATTESTATION:""}); const res=await verifier.fetch(request(),e);
  assert.equal(res.status,503); assert.equal(e.calls.length,0);
});
test("refuses outbound access without exact host allowlist",async()=>{
  const e=env({ALLOWED_SOURCE_HOSTS:""}); const res=await verifier.fetch(request(),e);
  assert.equal(res.status,503); assert.equal(e.calls.length,0);
});
test("requires internal service token",async()=>{
  assert.equal((await verifier.fetch(request(undefined,"wrong"),env())).status,401);
});
test("retrieves through VPC egress and reports retrieval, not claim verification",async()=>{
  const e=env(); const res=await verifier.fetch(request(),e); const data=await res.json();
  assert.equal(res.status,200); assert.equal(data.status,"retrieved_unverified");
  assert.equal(data.retrievalVerified,true); assert.equal(data.results[0].excerptMatched,true);
  assert.equal(data.results[0].supportsClaims,false);
  assert.equal(data.results[0].verificationStatus,"retrieved_unverified");
  assert.equal(e.calls.length,1); assert.equal(e.calls[0].options.redirect,"manual");
  assert.equal(e.calls[0].options.method,"GET");
});
test("rejects private, malformed, non-HTTPS and unlisted URLs before egress",async()=>{
  for (const bad of ["http://publisher.example/a","https://localhost/a","https://127.0.0.1/a",
    "https://2130706433/a","https://[::1]/a","https://publisher.example:8443/a",
    "https://attacker.example/a","https://publisher.example.evil.test/a"]) {
    const e=env(); const res=await verifier.fetch(request({protocolVersion:1,urls:[bad],draft:DRAFT}),e);
    assert.equal(res.status,400,bad); assert.equal(e.calls.length,0,bad);
  }
});
test("rejects redirects and never follows Location",async()=>{
  const e=env({EGRESS:{fetch:async()=>new Response(null,{status:302,headers:{location:"https://attacker.example/"}})}});
  assert.equal((await verifier.fetch(request(),e)).status,502); assert.equal(e.calls.length,1);
});
test("rejects oversized source bodies",async()=>{
  const e=env({EGRESS:{fetch:async()=>new Response(new ReadableStream({
    start(c){c.enqueue(new Uint8Array(1_000_001));c.close();}
  }),{status:200,headers:{"content-type":"text/plain"}})}});
  assert.equal((await verifier.fetch(request(),e)).status,502);
});
test("limits methods and route surface",async()=>{
  const e=env();
  assert.equal((await verifier.fetch(new Request("https://internal/v1/verify"),e)).status,405);
  assert.equal((await verifier.fetch(new Request("https://internal/healthz",{method:"POST",
    headers:{"x-aae-source-verifier-token":TOKEN}}),e)).status,404);
  assert.equal(e.calls.length,0);
});

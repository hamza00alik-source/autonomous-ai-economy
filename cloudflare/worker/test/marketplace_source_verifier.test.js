import test from "node:test";
import assert from "node:assert/strict";
import { verifyResearchSources } from "../src/marketplace_source_verifier.js";

const url = "https://example.com/reference";
const draft = "A detailed report explains the market and limitations. Source excerpt: This source describes the product and its documented capabilities in detail. Self-check: claims were checked against the supplied evidence.";

function response(payload, status=200) {
  return new Response(JSON.stringify(payload), {status, headers:{"content-type":"application/json"}});
}
function validPayload() {
  return {protocolVersion:1,status:"retrieved_unverified",retrievalVerified:true,results:[{
    requestedUrl:url,httpStatus:200,title:"Reference",finalUrl:url,supportsClaims:false,excerptMatched:true,verificationStatus:"retrieved_unverified",
    contentSha256:"a".repeat(64),fetchedAt:"2026-11-22T10:00:00.000Z",
    sourceExcerpt:"This source describes the product and its documented capabilities in detail.",
    draftExcerpt:"This source describes the product and its documented capabilities in detail.",
  }]};
}

test("research verification fails closed when service binding is absent", async()=>{
  const result=await verifyResearchSources({}, {title:"Research a software market"}, draft+" "+url);
  assert.equal(result.verified,false);
  assert.ok(result.blockers.includes("source_verifier_unavailable"));
});

test("non-research task does not call the verifier", async()=>{
  let called=false;
  const result=await verifyResearchSources({SOURCE_VERIFIER_TOKEN:"source-token",SOURCE_VERIFIER:{fetch:async()=>{called=true;}}},{title:"Write a short product summary"},draft);
  assert.equal(result.status,"not_required");
  assert.equal(called,false);
});

test("valid trusted verifier response is accepted", async()=>{
  let sent;
  const result=await verifyResearchSources({SOURCE_VERIFIER_TOKEN:"source-token",SOURCE_VERIFIER:{fetch:async(_url,init)=>{
    sent=JSON.parse(init.body); return response(validPayload());
  }}},{title:"Research a software market",description:"Compare current products"},draft+" "+url);
  assert.equal(result.verified,false);
  assert.equal(result.retrievalVerified,true);
  assert.equal(result.status,"retrieved_unverified");
  assert.equal(result.results.length,1);
  assert.equal(sent.protocolVersion,1);
  assert.deepEqual(sent.urls,[url]);
});

test("malformed, unsupported, or mismatched evidence is rejected", async()=>{
  for (const mutate of [
    p=>{p.results[0].supportsClaims=true;},
    p=>{p.results[0].excerptMatched=false;},
    p=>{p.results[0].requestedUrl="https://evil.example/";},
    p=>{p.results[0].draftExcerpt="not in draft";},
    p=>{p.results[0].contentSha256="invalid";},
    p=>{p.results[0].httpStatus=404;},
  ]) {
    const payload=validPayload(); mutate(payload);
    const result=await verifyResearchSources({SOURCE_VERIFIER_TOKEN:"source-token",SOURCE_VERIFIER:{fetch:async()=>response(payload)}},{title:"Research a software market"},draft+" "+url);
    assert.equal(result.verified,false);
    assert.ok(result.blockers.includes("source_verification_failed"));
  }
});

test("unsafe, non-public, malformed and non-default-port URLs are rejected before fetch", async()=>{
  for (const badUrl of [
    "https://localhost/reference",
    "https://foo.local/reference",
    "https://foo.internal/reference",
    "https://foo.onion/reference",
    "https://127.0.0.1/reference",
    "https://2130706433/reference",
    "https://[::1]/reference",
    "https://example.com:8443/reference",
    "http://example.com/reference",
  ]) {
    let called=false;
    const result=await verifyResearchSources({SOURCE_VERIFIER_TOKEN:"source-token",SOURCE_VERIFIER:{fetch:async()=>{called=true;}}},{title:"Research a software market"},draft+" "+badUrl);
    assert.equal(result.verified,false,badUrl);
    assert.equal(called,false,badUrl);
    assert.ok(result.blockers.includes("invalid_source_urls"),badUrl);
  }
});

test("unsafe verifier redirect destinations are rejected", async()=>{
  for (const finalUrl of [
    "http://example.com/reference",
    "https://localhost/reference",
    "https://127.0.0.1/reference",
    "https://example.com:8443/reference",
  ]) {
    const payload=validPayload(); payload.results[0].finalUrl=finalUrl;
    const result=await verifyResearchSources({SOURCE_VERIFIER_TOKEN:"source-token",SOURCE_VERIFIER:{fetch:async()=>response(payload)}},{title:"Research a software market"},draft+" "+url);
    assert.equal(result.verified,false,finalUrl);
    assert.ok(result.blockers.includes("source_verification_failed"),finalUrl);
  }
});

test("oversized source lists are rejected before calling the binding", async()=>{
  let called=false;
  const urls=Array.from({length:9},(_,i)=>"https://example.com/"+i).join(" ");
  const result=await verifyResearchSources({SOURCE_VERIFIER_TOKEN:"source-token",SOURCE_VERIFIER:{fetch:async()=>{called=true;}}},{title:"Research sources"},draft+" "+urls);
  assert.equal(result.verified,false);
  assert.equal(called,false);
  assert.ok(result.blockers.includes("too_many_research_sources"));
});

test("service errors fail closed without consuming error response body", async()=>{
  const errorResponse=new Response("service error body",{status:503});
  const result=await verifyResearchSources({SOURCE_VERIFIER_TOKEN:"source-token",SOURCE_VERIFIER:{fetch:async()=>errorResponse}},{title:"Research a software market"},draft+" "+url);
  assert.equal(result.verified,false);
  assert.ok(result.blockers.includes("source_verification_failed"));
  assert.equal(errorResponse.bodyUsed,false);
});

test("oversized verifier response is rejected while streaming without content-length", async()=>{
  const huge = "x".repeat(70000);
  const oversizedResponse = new Response(new ReadableStream({
    start(controller) {
      controller.enqueue(new TextEncoder().encode(huge));
      controller.close();
    },
  }), {status:200, headers:{"content-type":"application/json"}});
  const result=await verifyResearchSources({SOURCE_VERIFIER_TOKEN:"source-token",SOURCE_VERIFIER:{fetch:async()=>oversizedResponse}},{title:"Research a software market"},draft+" "+url);
  assert.equal(result.verified,false);
  assert.ok(result.blockers.includes("source_verification_failed"));
  assert.match(result.error,/too large/i);
});

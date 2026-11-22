import test from 'node:test';
import assert from 'node:assert/strict';
import reviewer from '../src/index.js';
const TOKEN='review-token',task={title:'Write a concise guide',description:'Use supplied facts.'};
const deliverable='A complete guide. Limitations: only supplied facts are covered.';
const requirements=[{kind:'acceptance_criterion',text:'Include limitations'}];
const validReview={pass:true,issues:[],reason:'The guide meets the criterion.',criteria:[{kind:'acceptance_criterion',criterion:'Include limitations',passed:true,evidence:'Limitations: only supplied facts are covered.'}]};
function env(overrides={}){const calls=[];return {calls,INTERNAL_REVIEW_TOKEN:TOKEN,EGRESS_POLICY_ATTESTATION:'aae-review-egress-v1',GEMINI_API_KEY:'test-key',EGRESS:{fetch:async(url,options)=>{calls.push({url,options});return new Response(JSON.stringify({candidates:[{content:{parts:[{text:JSON.stringify(validReview)}]}}]}),{status:200,headers:{'content-type':'application/json'}});}},...overrides};}
function req(token=TOKEN,payload={protocolVersion:1,task,deliverable,requirements,sourceEvidence:[]}){return new Request('https://internal/v1/review',{method:'POST',headers:{'content-type':'application/json','x-aae-independent-review-token':token},body:JSON.stringify(payload)});}
test('fails closed without VPC egress, Gateway attestation or Google key',async()=>{for(const overrides of [{EGRESS:undefined},{EGRESS_POLICY_ATTESTATION:''},{GEMINI_API_KEY:''}]){const e=env(overrides);const r=await reviewer.fetch(req(),e);assert.equal(r.status,503);assert.equal(e.calls.length,0);}});
test('requires internal token',async()=>{assert.equal((await reviewer.fetch(req('bad'),env())).status,401);});
test('calls Google through VPC egress and truthfully labels independent provider',async()=>{const e=env();const r=await reviewer.fetch(req(),e);const data=await r.json();assert.equal(r.status,200);assert.equal(data.provider,'google');assert.equal(data.independent,true);assert.equal(data.sameProvider,false);assert.equal(data.model,'gemini-3.8-flash');assert.match(e.calls[0].url,/generativelanguage\.googleapis\.com/);assert.equal(e.calls[0].options.redirect,'manual');assert.equal(e.calls[0].options.headers['x-goog-api-key'],'test-key');});
test('rejects invalid payload before provider call',async()=>{const e=env();const r=await reviewer.fetch(req(TOKEN,{protocolVersion:1,task,deliverable:1,requirements,sourceEvidence:[]}));assert.equal(r.status,400);assert.equal(e.calls.length,0);});
test('does not follow provider redirects',async()=>{const e=env({EGRESS:{fetch:async()=>new Response(null,{status:302,headers:{location:'https://attacker.example'}})}});assert.equal((await reviewer.fetch(req(),e)).status,502);});
test('rejects malformed model output',async()=>{const e=env({EGRESS:{fetch:async()=>new Response(JSON.stringify({candidates:[{content:{parts:[{text:'not json'}]}}]}),{status:200})}});assert.equal((await reviewer.fetch(req(),e)).status,502);});

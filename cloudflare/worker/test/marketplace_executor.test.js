import test from "node:test";
import assert from "node:assert/strict";
import { assessTask, executePrivateDraft } from "../src/marketplace_executor.js";

const goodDraft="Documentation draft: This guide explains the supplied software feature, its setup steps, expected behavior, and practical limitations. Source: https://example.com/docs. Self-check: verify every step against the current official documentation before use.";
const reviewerPass=JSON.stringify({pass:true,issues:[],reason:"The deliverable directly addresses the task and avoids unsupported claims.",criteria:[]});
function independentService(review=JSON.parse(reviewerPass)){return {fetch:async(url)=>new Response(JSON.stringify(String(url).endsWith("/healthz")?{ok:true}:{protocolVersion:1,provider:"google",model:"gemini-3.8-flash",independent:true,sameProvider:false,review}),{status:200,headers:{"content-type":"application/json"}})};}
function independentEnv(AI,review=JSON.parse(reviewerPass)){return {AI,INDEPENDENT_REVIEWER:independentService(review),INDEPENDENT_REVIEW_TOKEN:"review-token",INDEPENDENT_REVIEW_ENABLED:"true"};}

test("screens eligible tasks into private draft lane",()=>{
  assert.equal(assessTask({id:"t1",title:"Review open source docs",description:"Review docs and suggest improvements",eligible:true,reward_usdc:"1.00"}).eligible,true);
});
test("preserves buyer acceptance criteria and delivery constraints",()=>{
  const result=assessTask({title:"Review docs",description:"Produce a review",reward_usdc:"1.00",acceptance_criteria:["Link every factual claim"],required_deliverables:["Markdown report"],constraints:["No paid APIs"],output_format:"Markdown"});
  assert.deepEqual(result.acceptanceCriteria,["Link every factual claim"]);
  assert.deepEqual(result.requiredDeliverables,["Markdown report"]);
  assert.deepEqual(result.constraints,["No paid APIs"]);
  assert.equal(result.outputFormat,"Markdown");
});
test("blocks stake and external publishing risks",()=>{
  for(const task of [{title:"Deposit required",description:"Stake to enter"},{title:"Post social content",description:"Publish a marketing post"},{title:"Connect wallet",description:"Sign transaction"}]) assert.equal(assessTask(task).eligible,false);
});
test("blocks placeholder titles and unsupported media production",()=>{
  for(const task of [{title:"## Title",description:"Create a useful deliverable"},{title:"Untitled",description:"Write a short note"},{title:"Create a story",description:"Produce the final video with recorded voiceover"}]) assert.equal(assessTask(task).eligible,false);
  assert.ok(assessTask({title:"## Title",description:"Create a useful deliverable"}).reasons.includes("malformed_task_title"));
  assert.ok(assessTask({title:"Create a story",description:"Produce the final video with recorded voiceover"}).reasons.includes("unsupported_deliverable"));
});
test("allows a well-formed text task",()=>{
  assert.equal(assessTask({title:"Review open source documentation",description:"Write a concise documentation review and list actionable improvements.",eligible:true,reward_usdc:"1.00"}).eligible,true);
});
test("blocks credits-only task",()=>{
  assert.ok(assessTask({title:"task",description:"work",reward_credits:20,credits_only:true}).reasons.includes("non_cash_reward"));
});
test("requires a positive USDC reward",()=>{
  for(const reward of [null,undefined,0,"0","-1","pending","1 ETH"]) {
    const result=assessTask({title:"Review documentation",description:"Write a useful documentation review.",reward});
    assert.equal(result.eligible,false);
    assert.ok(result.reasons.includes("reward_not_positive_verified_usdc"));
  }
  assert.equal(assessTask({title:"Review documentation",description:"Write a useful documentation review.",reward:"1.000000"}).eligible,true);
});
test("private execution requires review and takes no external action",async()=>{
  const outputs=[goodDraft,reviewerPass];
  const env=independentEnv({run:async()=>({response:outputs.shift()})});
  const result=await executePrivateDraft(env,{id:"t",title:"Prepare a concise software guide",description:"Summarize the supplied material",eligible:true,reward_usdc:"0.1"});
  assert.equal(result.status,"submission_candidate");
  assert.equal(result.externalActionsTaken,false);
  assert.equal(result.agentTeam.length,3);
  assert.equal(result.submissionReady,true);
  assert.match(result.deliverableSha256,/^[a-f0-9]{64}$/);
  assert.ok(result.qa.checks.some(check=>check.id==="independent_provider_review"&&check.passed));
  assert.equal(result.qa.same_model_review.pass, true);
  assert.equal(Object.hasOwn(result.qa, "independent_review"), true);
  assert.equal(result.qa.independent_review.provider,"google");
  assert.equal(result.qa.independent_review.independent,true);
});
test("criterion failure blocks readiness after bounded revision",async()=>{
  const criterion="Include limitations";
  const outputs=[goodDraft,JSON.stringify({pass:false,issues:["Add limitations"],reason:"Missing section",criteria:[{kind:"acceptance_criterion",criterion,passed:false,evidence:"Documentation draft"}]}),goodDraft,JSON.stringify({pass:false,issues:["Still missing limitations"],reason:"Revision did not fix the gap",criteria:[{kind:"acceptance_criterion",criterion,passed:false,evidence:"Documentation draft"}]})];
  const result=await executePrivateDraft(independentEnv({run:async()=>({response:outputs.shift()})},{pass:false,issues:["Still missing limitations"],reason:"Revision did not fix the gap",criteria:[{kind:"acceptance_criterion",criterion,passed:false,evidence:"Documentation draft"}]}),{id:"t",title:"Draft supplied documentation summary",description:"Summarize the provided documentation content",eligible:true,reward_usdc:"0.1",acceptance_criteria:[criterion]});
  assert.equal(result.submissionReady,false);
  assert.ok(result.qa.blockers.includes("independent_provider_review_not_passed"));
  assert.ok(result.qa.blockers.includes("acceptance_criteria_not_verified"));
});
test("rejects empty specialist output",async()=>{
  await assert.rejects(()=>executePrivateDraft(independentEnv({run:async()=>({})}),{title:"Draft a concise note",description:"Write a concise note using provided material",eligible:true,reward_usdc:"1.00"}),/specialist agent returned no usable output/);
});
test("blocks code execution requirements without sandbox",()=>{
  const result=assessTask({title:"Test the submitted Python script",description:"Run the script and execute the unit tests before delivery.",reward_usdc:"1.00"});
  assert.equal(result.eligible,false);
  assert.ok(result.reasons.includes("runtime_verification_unavailable"));
});
test("blocks unsupported file formats",()=>{
  for(const outputFormat of ["PDF","DOCX","XLSX","ZIP","GLB"]) {
    const result=assessTask({title:"Prepare deliverable",description:"Create a written summary.",reward_usdc:"1.00",output_format:outputFormat});
    assert.equal(result.eligible,false,outputFormat);
    assert.ok(result.reasons.includes("unsupported_artifact_format"),outputFormat);
  }
});
test("research tasks without verifier are blocked before model inference",async()=>{
  let aiCalls=0;
  const result=await executePrivateDraft(independentEnv({run:async()=>{aiCalls++;return {response:goodDraft};}}),{id:"research",title:"Research software documentation",description:"Compare documented features",eligible:true,reward_usdc:"0.1"});
  assert.equal(result.status,"blocked");
  assert.equal(result.submissionReady,undefined);
  assert.equal(aiCalls,0);
  assert.ok(result.assessment.reasons.includes("source_verifier_unavailable"));
  assert.equal(result.externalActionsTaken,false);
});


test("blocks unsuitable Base listings that disguise production or non-USDC work",()=>{
  const video=assessTask({title:"制作一个约20分钟的《西游记》视频",description:"制作一个约20分钟、内容完整的视频，包含分镜、配音、字幕、音效和最终导出。",reward:"1.00"});
  assert.equal(video.eligible,false);
  assert.ok(video.reasons.includes("unsupported_deliverable"));
  const settlement=assessTask({title:"Test Base-to-Robinhood settlement",description:"Test one authorized end-to-end settlement attempt using an authorized Base test account and Robinhood destination with controlled funds.",reward:"1.00"});
  assert.equal(settlement.eligible,false);
  assert.ok(settlement.reasons.some(reason=>reason.startsWith("blocked_risk_pattern:")));
  const token=assessTask({title:"FlapJax Q103 first-timers only",description:"List treasury outflows and group recipients by first BNB funder. 100,000 FLAPJAX each, first-timers only.",reward:"1.00"});
  assert.equal(token.eligible,false);
  assert.ok(token.reasons.some(reason=>reason.startsWith("blocked_risk_pattern:")));
});


test("independent reviewer is a hard preflight gate before any specialist inference",async()=>{
  let aiCalls=0;
  const result=await executePrivateDraft({AI:{run:async()=>{aiCalls++;return {response:goodDraft};}}},{
    id:"no-reviewer",title:"Prepare a concise software guide",description:"Summarize supplied documentation.",
    eligible:true,reward_usdc:"1.00",
  });
  assert.equal(result.status,"blocked");
  assert.equal(aiCalls,0);
  assert.ok(result.assessment.reasons.includes("independent_provider_unavailable"));
});

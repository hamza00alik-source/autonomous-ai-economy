import test from "node:test";
import assert from "node:assert/strict";
import { canonicalAgentKeyPayload } from "../src/agent_api_identity.js";

test("agent key registration payload canonicalization is deterministic",()=>{
  assert.equal(canonicalAgentKeyPayload({b:2,a:1}),canonicalAgentKeyPayload({a:1,b:2}));
});

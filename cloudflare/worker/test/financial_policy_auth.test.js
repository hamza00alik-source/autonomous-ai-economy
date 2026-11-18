import test from "node:test";
import assert from "node:assert/strict";
import {
  canonicalizeFinancialPolicy,
  financialPublicKeyFingerprint,
  verifyOwnerSignedFinancialPolicy,
  validateFinancialPolicy
} from "../src/financial_policy_auth.js";

const encoder = new TextEncoder();
function base64url(bytes) {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/=/g, "").replace(/\\+/g, "-").replace(/\\//g, "_");
}
async function fixture() {
  const pair = await crypto.subtle.generateKey({ name: "Ed25519" }, true, ["sign", "verify"]);
  const signerJwk = await crypto.subtle.exportKey("jwk", pair.publicKey);
  const fingerprint = await financialPublicKeyFingerprint(signerJwk);
  const policy = {
    policy_id: "agent-policy-01",
    version: 1,
    owner_id: "owner-01",
    agent_id: "agent-01",
    currency: "USD",
    per_transaction_limit_minor: 2500,
    daily_spend_limit_minor: 10000,
    allowed_destinations: ["provider:storage:account-1", "provider:compute:account-2"]
  };
  const canonicalPayload = canonicalizeFinancialPolicy(policy);
  const signature = new Uint8Array(await crypto.subtle.sign({ name: "Ed25519" }, pair.privateKey, encoder.encode(canonicalPayload)));
  const common = {
    policy, canonicalPayload, signatureBase64Url: base64url(signature),
    signerKeyFingerprint: fingerprint, signerJwk,
    owner: { participant_id: "owner-01", participant_type: "owner", status: "active" },
    signer: { participant_id: "operator-01", participant_type: "operator", status: "active", owner_id: "owner-01", key_fingerprint: fingerprint },
    agent: { participant_id: "agent-01", participant_type: "agent", status: "active", owner_id: "owner-01", operator_id: "operator-01" }
  };
  return { ...common, pair };
}

test("verifies an Ed25519 owner-operator signature for the exact canonical policy", async () => {
  const input = await fixture();
  const result = await verifyOwnerSignedFinancialPolicy(input);
  assert.equal(result.ok, true);
  assert.equal(result.policy.policy_id, "agent-policy-01");
});

test("rejects policy mutation even when the stored signature is unchanged", async () => {
  const input = await fixture();
  input.policy.daily_spend_limit_minor = 999999;
  input.canonicalPayload = canonicalizeFinancialPolicy(input.policy);
  const result = await verifyOwnerSignedFinancialPolicy(input);
  assert.deepEqual(result, { ok: false, reason: "invalid_owner_signature" });
});

test("rejects a signer who is not the active operator bound to the agent", async () => {
  const input = await fixture();
  input.signer.participant_id = "other-operator";
  assert.equal((await verifyOwnerSignedFinancialPolicy(input)).reason, "signer_not_authorized_operator");
});

test("rejects suspended owners, operators, and agents", async () => {
  for (const field of ["owner", "signer", "agent"]) {
    const input = await fixture();
    input[field].status = "suspended";
    const result = await verifyOwnerSignedFinancialPolicy(input);
    assert.equal(result.ok, false);
  }
});

test("rejects private JWK material and mismatched public-key fingerprints", async () => {
  const input = await fixture();
  input.signerJwk.d = "must-not-be-stored";
  assert.equal((await verifyOwnerSignedFinancialPolicy(input)).reason, "signer_key_invalid");
  const clean = await fixture();
  clean.signerKeyFingerprint = "0".repeat(64);
  assert.equal((await verifyOwnerSignedFinancialPolicy(clean)).reason, "signer_key_fingerprint_mismatch");
});

test("policy validation rejects wildcards, duplicate destinations, and unsafe limits", async () => {
  const input = await fixture();
  assert.equal(validateFinancialPolicy({ ...input.policy, allowed_destinations: ["*"] }), "invalid_destination");
  assert.equal(validateFinancialPolicy({ ...input.policy, allowed_destinations: ["same", "same"] }), "duplicate_destination");
  assert.equal(validateFinancialPolicy({ ...input.policy, per_transaction_limit_minor: 10001 }), "transaction_limit_exceeds_daily_limit");
});

test("rejects extra policy fields and noncanonical serialization", async () => {
  const input = await fixture();
  assert.equal(validateFinancialPolicy({ ...input.policy, allow_all: true }), "policy_schema_mismatch");
  const noncanonical = await fixture();
  noncanonical.canonicalPayload = JSON.stringify(noncanonical.policy);
  assert.equal((await verifyOwnerSignedFinancialPolicy(noncanonical)).reason, "noncanonical_policy_payload");
});

test("rejects a valid signature attached to a different owner-agent relationship", async () => {
  const input = await fixture();
  input.agent.owner_id = "other-owner";
  assert.equal((await verifyOwnerSignedFinancialPolicy(input)).reason, "agent_not_active_or_owned");
});

test("cloud policy loader refuses malformed agent identifiers before querying D1", async () => {
  const { loadActiveCloudFinancialPolicy } = await import("../src/financial_policy_auth.js");
  let queried = false;
  const result = await loadActiveCloudFinancialPolicy({ prepare() { queried = true; throw new Error("unexpected query"); } }, "bad id");
  assert.deepEqual(result, { ok: false, reason: "invalid_agent_id" });
  assert.equal(queried, false);
});

test("cloud policy loader fails closed when no active policy exists", async () => {
  const { loadActiveCloudFinancialPolicy } = await import("../src/financial_policy_auth.js");
  let sql = "";
  const db = { prepare(query) { sql = query; return { bind(value) { assert.equal(value, "agent-01"); return { first: async () => null }; } }; } };
  const result = await loadActiveCloudFinancialPolicy(db, "agent-01");
  assert.deepEqual(result, { ok: false, reason: "active_policy_not_found" });
  assert.match(sql, /p.status='active'/);
  assert.match(sql, /JOIN financial_participants s/);
  assert.match(sql, /JOIN financial_participants a/);
});

test("cloud policy loader verifies stored signature and relational bindings before authorizing", async () => {
  const { loadActiveCloudFinancialPolicy } = await import("../src/financial_policy_auth.js");
  const input = await fixture();
  const row = {
    policy_id: input.policy.policy_id, version: input.policy.version,
    owner_id: input.policy.owner_id, agent_id: input.policy.agent_id,
    signer_id: input.signer.participant_id, currency: input.policy.currency,
    per_transaction_limit_minor: input.policy.per_transaction_limit_minor,
    daily_spend_limit_minor: input.policy.daily_spend_limit_minor,
    allowed_destinations_json: JSON.stringify(input.policy.allowed_destinations),
    canonical_payload: input.canonicalPayload, signature_base64url: input.signatureBase64Url,
    signer_key_fingerprint: input.signerKeyFingerprint, status: "active",
    owner_participant_id: input.owner.participant_id, owner_type: "owner", owner_status: "active",
    signer_participant_id: input.signer.participant_id, signer_type: "operator", signer_status: "active",
    signer_owner_id: input.signer.owner_id, signer_public_key_jwk: JSON.stringify(input.signerJwk),
    signer_fingerprint: input.signerKeyFingerprint,
    agent_participant_id: input.agent.participant_id, agent_type: "agent", agent_status: "active",
    agent_owner_id: input.agent.owner_id, agent_operator_id: input.agent.operator_id
  };
  const db = { prepare(query) {
    assert.match(query, /financial_policies/);
    return { bind(value) { assert.equal(value, "agent-01"); return { first: async () => row }; } };
  } };
  const result = await loadActiveCloudFinancialPolicy(db, "agent-01");
  assert.equal(result.ok, true);
  assert.equal(result.policy.policy_id, "agent-policy-01");
  row.agent_operator_id = "different-operator";
  const rejected = await loadActiveCloudFinancialPolicy(db, "agent-01");
  assert.equal(rejected.ok, false);
  assert.equal(rejected.reason, "signer_not_authorized_operator");
});

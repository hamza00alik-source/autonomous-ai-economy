import test from "node:test";
import assert from "node:assert/strict";
import { webcrypto } from "node:crypto";
import { AgentKeyVaultCore } from "../src/agent_key_vault_core.js";

if (!globalThis.crypto) Object.defineProperty(globalThis, "crypto", { value: webcrypto });
const encoder = new TextEncoder();
const decode = value => Buffer.from(value, "base64url");
const hex = bytes => Buffer.from(bytes).toString("hex");
async function hash(value) {
  return hex(await crypto.subtle.digest("SHA-256", encoder.encode(value)));
}
const TEST_SECRET = "test-only-agent-key-encryption-secret-0123456789";
function storageHarness() {
  const values = new Map();
  return {
    values,
    storage: {
      async get(key) { return structuredClone(values.get(key)); },
      async put(key, value) { values.set(key, structuredClone(value)); },
    },
  };
}
function vaultFor(harness, id = "unit-test-agent-key-vault", secret = TEST_SECRET) {
  return new AgentKeyVaultCore({
    id: { toString: () => id },
    storage: harness.storage,
    blockConcurrencyWhile: callback => callback(),
  }, { AAE_AGENT_KEY_ENCRYPTION_SECRET: secret });
}

test("agent identity survives restart using authenticated ciphertext, not CryptoKey structured cloning", async () => {
  const harness = storageHarness();
  const identity = await vaultFor(harness).ensureIdentity("agent-001");
  const stored = harness.values.get("agent-api-identity");
  assert.equal(stored.privateKey, undefined);
  assert.equal(stored.sealedPrivateKey.version, 1);
  assert.ok(stored.sealedPrivateKey.ciphertext);
  assert.equal(JSON.stringify(stored).includes("privateKey"), false);
  assert.equal(identity.public_key_jwk.d, undefined);

  const restarted = vaultFor(harness);
  const proof = await restarted.createEnrollmentProof("agent-001");
  const publicKey = await crypto.subtle.importKey(
    "jwk", proof.public_key_jwk, { name: "Ed25519" }, false, ["verify"]
  );
  assert.equal(await crypto.subtle.verify(
    { name: "Ed25519" }, publicKey, decode(proof.proof_signature),
    encoder.encode("AAE-AGENT-KEY-PROOF:v1:" + identity.key_fingerprint)
  ), true);
});

test("vault signs only the owning agent invoice request and binds the exact body", async () => {
  const harness = storageHarness();
  const vault = vaultFor(harness);
  const identity = await vault.ensureIdentity("agent-001");
  const body = '{"amount":"1.00","currency":"USDC"}';
  const path = "/v1/agents/agent-001/receiving-invoices";
  const timestamp = 1_800_000_000_000;
  const nonce = "n".repeat(24);
  const headers = await vault.signInvoiceRequest({
    agentId: "agent-001", method: "POST", path, body, timestamp, nonce,
  });
  const publicKey = await crypto.subtle.importKey(
    "jwk", identity.public_key_jwk, { name: "Ed25519" }, false, ["verify"]
  );
  const canonical = ["POST", path, String(timestamp), nonce, await hash(body)].join("\n");
  assert.equal(headers["X-AAE-Key"], identity.key_fingerprint);
  assert.equal(await crypto.subtle.verify(
    { name: "Ed25519" }, publicKey, decode(headers["X-AAE-Signature"]),
    encoder.encode(canonical)
  ), true);
  await assert.rejects(() => vault.signInvoiceRequest({
    agentId: "agent-001", method: "POST", path: "/v1/owner/finance/transfer", body,
  }), /only the agent's invoice-creation request may be signed/);
});

test("encrypted key is bound to its Durable Object identity and rejects tampering", async () => {
  const harness = storageHarness();
  const identity = await vaultFor(harness, "object-one").ensureIdentity("agent-001");
  const wrongObject = vaultFor(harness, "object-two");
  await assert.rejects(() => wrongObject.createEnrollmentProof("agent-001"));
  const record = harness.values.get("agent-api-identity");
  const ciphertext = decode(record.sealedPrivateKey.ciphertext);
  ciphertext[0] ^= 1;
  record.sealedPrivateKey.ciphertext = Buffer.from(ciphertext).toString("base64url");
  harness.values.set("agent-api-identity", record);
  await assert.rejects(() => vaultFor(harness, "object-one").createEnrollmentProof("agent-001"), /authenticated/);
  assert.equal(identity.key_fingerprint.length, 64);
});

test("vault fails closed when its out-of-band encryption secret is missing", async () => {
  const harness = storageHarness();
  await assert.rejects(
    () => vaultFor(harness, "no-secret", "").ensureIdentity("agent-001"),
    /encryption secret is not configured/
  );
});

test("vault cannot be rebound to another agent", async () => {
  const harness = storageHarness();
  const vault = vaultFor(harness);
  await vault.ensureIdentity("agent-001");
  await assert.rejects(() => vault.ensureIdentity("agent-002"), /another agent/);
});

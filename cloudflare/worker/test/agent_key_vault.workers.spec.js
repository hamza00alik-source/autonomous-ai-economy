import { env } from "cloudflare:workers";
import { evictDurableObject } from "cloudflare:test";
import { describe, expect, it } from "vitest";

const encoder = new TextEncoder();
const decode = value => Uint8Array.from(
  atob(value.replace(/-/g, "+").replace(/_/g, "/")),
  character => character.charCodeAt(0),
);

async function callVault(stub, operation, extra = {}) {
  const response = await stub.fetch("https://vault.internal/operation", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ operation, agent_id: "agent-runtime-001", ...extra }),
  });
  const payload = await response.json();
  expect(response.status).toBe(200);
  expect(payload.error).toBeUndefined();
  return payload.result;
}

describe("AgentKeyVault in the Cloudflare Workers runtime", () => {
  it("persists a non-exportable Ed25519 CryptoKey across Durable Object eviction", async () => {
    const id = env.AGENT_KEY_VAULT.idFromName("runtime-persistence-agent-001");
    const stub = env.AGENT_KEY_VAULT.get(id);

    const firstIdentity = await callVault(stub, "ensure_identity");
    expect(firstIdentity.agent_id).toBe("agent-runtime-001");
    expect(firstIdentity.public_key_jwk.d).toBeUndefined();
    expect(firstIdentity.key_fingerprint).toMatch(/^[a-f0-9]{64}$/);

    await evictDurableObject(stub);

    const proof = await callVault(stub, "create_enrollment_proof");
    expect(proof.public_key_jwk).toEqual(firstIdentity.public_key_jwk);

    const publicKey = await crypto.subtle.importKey(
      "jwk", proof.public_key_jwk, { name: "Ed25519" }, false, ["verify"],
    );
    const valid = await crypto.subtle.verify(
      { name: "Ed25519" },
      publicKey,
      decode(proof.proof_signature),
      encoder.encode("AAE-AGENT-KEY-PROOF:v1:" + firstIdentity.key_fingerprint),
    );
    expect(valid).toBe(true);

    const body = JSON.stringify({ amount: "1.00", currency: "USDC" });
    const headers = await callVault(stub, "sign_invoice_request", {
      args: {
        agentId: "agent-runtime-001",
        method: "POST",
        path: "/v1/agents/agent-runtime-001/receiving-invoices",
        body,
        timestamp: Date.now(),
        nonce: "runtime-nonce-1234567890",
      },
    });
    expect(headers["X-AAE-Key"]).toBe(firstIdentity.key_fingerprint);
    expect(headers["X-AAE-Signature"]).toMatch(/^[A-Za-z0-9_-]+$/);
  });

  it("keeps separate Durable Object identities isolated", async () => {
    const firstId = env.AGENT_KEY_VAULT.idFromName("runtime-isolation-agent-001");
    const secondId = env.AGENT_KEY_VAULT.idFromName("runtime-isolation-agent-002");
    const first = env.AGENT_KEY_VAULT.get(firstId);
    const second = env.AGENT_KEY_VAULT.get(secondId);

    const firstIdentity = await callVault(first, "ensure_identity");
    const secondIdentity = await callVault(second, "ensure_identity");
    expect(firstIdentity.key_fingerprint).not.toBe(secondIdentity.key_fingerprint);

    const mismatch = await second.fetch("https://vault.internal/operation", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        operation: "ensure_identity",
        agent_id: "agent-runtime-999",
      }),
    });
    expect(mismatch.status).toBe(400);
  });
});

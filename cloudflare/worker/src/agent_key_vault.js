const encoder = new TextEncoder();
const ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{2,79}$/;
const NONCE = /^[A-Za-z0-9_-]{16,96}$/;

function toBase64Url(bytes) {
  return btoa(String.fromCharCode(...new Uint8Array(bytes)))
    .replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}

async function sha256Hex(value) {
  const digest = await crypto.subtle.digest(
    "SHA-256",
    typeof value === "string" ? encoder.encode(value) : value
  );
  return [...new Uint8Array(digest)]
    .map(byte => byte.toString(16).padStart(2, "0")).join("");
}

function publicIdentity(record) {
  return {
    agent_id: record.agentId,
    public_key_jwk: record.publicKeyJwk,
    key_fingerprint: record.keyFingerprint,
  };
}

/**
 * One Durable Object instance is assigned to one agent ID by the Worker.
 * Its private CryptoKey is persisted using Durable Object structured-clone
 * storage. Only public identity and narrowly scoped invoice-auth signatures
 * leave this object.
 */
export class AgentKeyVault {
  constructor(ctx, env) {
    this.ctx = ctx;
    this.env = env;
  }

  async ensureIdentity(agentId) {
    if (!ID.test(agentId || "")) throw new Error("valid agent ID is required");

    const existing = await this.ctx.storage.get("agent-api-identity");
    if (existing) {
      if (existing.agentId !== agentId) {
        throw new Error("vault is already bound to another agent");
      }
      return publicIdentity(existing);
    }

    return this.ctx.blockConcurrencyWhile(async () => {
      const lockedExisting = await this.ctx.storage.get("agent-api-identity");
      if (lockedExisting) {
        if (lockedExisting.agentId !== agentId) {
          throw new Error("vault is already bound to another agent");
        }
        return publicIdentity(lockedExisting);
      }

      const pair = await crypto.subtle.generateKey(
        { name: "Ed25519" }, false, ["sign", "verify"]
      );
      const exported = await crypto.subtle.exportKey("jwk", pair.publicKey);
      const publicKeyJwk = { crv: "Ed25519", kty: "OKP", x: exported.x };
      const canonicalJwk = JSON.stringify(publicKeyJwk);
      const record = {
        agentId,
        privateKey: pair.privateKey,
        publicKeyJwk,
        keyFingerprint: await sha256Hex(canonicalJwk),
        createdAt: new Date().toISOString(),
      };

      // CryptoKey is stored as a structured-clone value; never export private JWK.
      await this.ctx.storage.put("agent-api-identity", record);
      return publicIdentity(record);
    });
  }

  async createEnrollmentProof(agentId) {
    const identity = await this.ensureIdentity(agentId);
    const record = await this.ctx.storage.get("agent-api-identity");
    const signature = await crypto.subtle.sign(
      { name: "Ed25519" },
      record.privateKey,
      encoder.encode("AAE-AGENT-KEY-PROOF:v1:" + identity.key_fingerprint)
    );
    return {
      public_key_jwk: identity.public_key_jwk,
      proof_signature: toBase64Url(signature),
    };
  }

  async signInvoiceRequest({ agentId, method, path, body, timestamp = Date.now(), nonce } = {}) {
    if (!ID.test(agentId || "") || method !== "POST" ||
        path !== "/v1/agents/" + agentId + "/receiving-invoices" ||
        typeof body !== "string" || !Number.isSafeInteger(timestamp)) {
      throw new Error("only the agent's invoice-creation request may be signed");
    }
    const record = await this.ctx.storage.get("agent-api-identity");
    if (!record || record.agentId !== agentId) {
      throw new Error("agent API identity has not been initialized");
    }
    const requestNonce = nonce || toBase64Url(crypto.getRandomValues(new Uint8Array(24)));
    if (!NONCE.test(requestNonce)) throw new Error("invalid request nonce");

    const canonical = [
      method, path, String(timestamp), requestNonce, await sha256Hex(body),
    ].join("\n");
    const signature = await crypto.subtle.sign(
      { name: "Ed25519" }, record.privateKey, encoder.encode(canonical)
    );
    return {
      "X-AAE-Key": record.keyFingerprint,
      "X-AAE-Timestamp": String(timestamp),
      "X-AAE-Nonce": requestNonce,
      "X-AAE-Signature": toBase64Url(signature),
      "Content-Type": "application/json",
    };
  }
}

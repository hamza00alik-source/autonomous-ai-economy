const encoder = new TextEncoder();
const ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{2,79}$/;
const NONCE = /^[A-Za-z0-9_-]{16,96}$/;
const RECORD_KEY = "agent-api-identity";
const RECORD_VERSION = 1;

function toBase64Url(bytes) {
  return btoa(String.fromCharCode(...new Uint8Array(bytes)))
    .replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}
function fromBase64Url(value) {
  if (typeof value !== "string" || !/^[A-Za-z0-9_-]+$/.test(value)) throw new Error("invalid encrypted key record");
  return Uint8Array.from(atob(value.replace(/-/g, "+").replace(/_/g, "/")), c => c.charCodeAt(0));
}
async function sha256Hex(value) {
  const digest = await crypto.subtle.digest("SHA-256", typeof value === "string" ? encoder.encode(value) : value);
  return [...new Uint8Array(digest)].map(byte => byte.toString(16).padStart(2, "0")).join("");
}
function publicIdentity(record) {
  return { agent_id: record.agentId, public_key_jwk: record.publicKeyJwk, key_fingerprint: record.keyFingerprint };
}

/**
 * Private Ed25519 PKCS#8 bytes are AES-GCM encrypted before Durable Object
 * storage. Each use decrypts in memory and imports a non-extractable key.
 * The HKDF input secret is provisioned out of band as
 * AAE_AGENT_KEY_ENCRYPTION_SECRET; it must never be committed to source.
 * CryptoKey structured cloning is not supported by the workerd runtime.
 */
export class AgentKeyVaultCore {
  constructor(ctx, env) { this.ctx = ctx; this.env = env; }

  async wrappingKey(agentId, salt) {
    const secret = this.env?.AAE_AGENT_KEY_ENCRYPTION_SECRET;
    if (typeof secret !== "string" || encoder.encode(secret).length < 32) {
      throw new Error("agent key vault encryption secret is not configured");
    }
    const objectId = this.ctx.id?.toString?.();
    if (!objectId) throw new Error("stable Durable Object identity is unavailable");
    const material = await crypto.subtle.importKey("raw", encoder.encode(secret), "HKDF", false, ["deriveKey"]);
    return crypto.subtle.deriveKey({
      name: "HKDF", hash: "SHA-256", salt,
      info: encoder.encode("AAE-AGENT-KEY-VAULT:v1:" + objectId + ":" + agentId),
    }, material, { name: "AES-GCM", length: 256 }, false, ["encrypt", "decrypt"]);
  }

  async sealPrivateKey(agentId, privateKey) {
    const pkcs8 = await crypto.subtle.exportKey("pkcs8", privateKey);
    const salt = crypto.getRandomValues(new Uint8Array(32));
    const iv = crypto.getRandomValues(new Uint8Array(12));
    const key = await this.wrappingKey(agentId, salt);
    const ciphertext = await crypto.subtle.encrypt({
      name: "AES-GCM", iv,
      additionalData: encoder.encode("AAE-AGENT-KEY-RECORD:v1:" + agentId),
    }, key, pkcs8);
    return { version: RECORD_VERSION, salt: toBase64Url(salt), iv: toBase64Url(iv), ciphertext: toBase64Url(ciphertext) };
  }

  async openPrivateKey(agentId, sealed) {
    if (!sealed || sealed.version !== RECORD_VERSION) throw new Error("unsupported encrypted key record");
    const key = await this.wrappingKey(agentId, fromBase64Url(sealed.salt));
    let pkcs8;
    try {
      pkcs8 = await crypto.subtle.decrypt({
        name: "AES-GCM", iv: fromBase64Url(sealed.iv),
        additionalData: encoder.encode("AAE-AGENT-KEY-RECORD:v1:" + agentId),
      }, key, fromBase64Url(sealed.ciphertext));
    } catch {
      throw new Error("agent private key could not be authenticated");
    }
    return crypto.subtle.importKey("pkcs8", pkcs8, { name: "Ed25519" }, false, ["sign"]);
  }

  async loadIdentity(agentId) {
    const record = await this.ctx.storage.get(RECORD_KEY);
    if (!record) return null;
    if (record.agentId !== agentId) throw new Error("vault is already bound to another agent");
    return { ...record, privateKey: await this.openPrivateKey(agentId, record.sealedPrivateKey) };
  }

  async ensureIdentity(agentId) {
    if (!ID.test(agentId || "")) throw new Error("valid agent ID is required");
    const existing = await this.ctx.storage.get(RECORD_KEY);
    if (existing) {
      if (existing.agentId !== agentId) throw new Error("vault is already bound to another agent");
      return publicIdentity(existing);
    }
    return this.ctx.blockConcurrencyWhile(async () => {
      const lockedExisting = await this.ctx.storage.get(RECORD_KEY);
      if (lockedExisting) {
        if (lockedExisting.agentId !== agentId) throw new Error("vault is already bound to another agent");
        return publicIdentity(lockedExisting);
      }
      // Extractability is temporary and used only to encrypt PKCS#8 immediately.
      const pair = await crypto.subtle.generateKey({ name: "Ed25519" }, true, ["sign", "verify"]);
      const exported = await crypto.subtle.exportKey("jwk", pair.publicKey);
      const publicKeyJwk = { crv: "Ed25519", kty: "OKP", x: exported.x };
      const record = {
        agentId,
        sealedPrivateKey: await this.sealPrivateKey(agentId, pair.privateKey),
        publicKeyJwk,
        keyFingerprint: await sha256Hex(JSON.stringify(publicKeyJwk)),
        createdAt: new Date().toISOString(),
      };
      await this.ctx.storage.put(RECORD_KEY, record);
      return publicIdentity(record);
    });
  }

  async createEnrollmentProof(agentId) {
    const identity = await this.ensureIdentity(agentId);
    const record = await this.loadIdentity(agentId);
    const signature = await crypto.subtle.sign(
      { name: "Ed25519" }, record.privateKey,
      encoder.encode("AAE-AGENT-KEY-PROOF:v1:" + identity.key_fingerprint)
    );
    return { public_key_jwk: identity.public_key_jwk, proof_signature: toBase64Url(signature) };
  }

  async signInvoiceRequest({ agentId, method, path, body, timestamp = Date.now(), nonce } = {}) {
    if (!ID.test(agentId || "") || method !== "POST" ||
        path !== "/v1/agents/" + agentId + "/receiving-invoices" ||
        typeof body !== "string" || !Number.isSafeInteger(timestamp)) {
      throw new Error("only the agent's invoice-creation request may be signed");
    }
    const record = await this.loadIdentity(agentId);
    if (!record) throw new Error("agent API identity has not been initialized");
    const requestNonce = nonce || toBase64Url(crypto.getRandomValues(new Uint8Array(24)));
    if (!NONCE.test(requestNonce)) throw new Error("invalid request nonce");
    const canonical = [method, path, String(timestamp), requestNonce, await sha256Hex(body)].join("\n");
    const signature = await crypto.subtle.sign({ name: "Ed25519" }, record.privateKey, encoder.encode(canonical));
    return {
      "X-AAE-Key": record.keyFingerprint,
      "X-AAE-Timestamp": String(timestamp),
      "X-AAE-Nonce": requestNonce,
      "X-AAE-Signature": toBase64Url(signature),
      "Content-Type": "application/json",
    };
  }
}

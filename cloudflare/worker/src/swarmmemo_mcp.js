const MCP_ENDPOINT = "https://swarmmemo.com/mcp?toolsets=all";
const MCP_VERSION = "2025-03-26";
const MAX_MCP_BYTES = 128_000;

function parseMcpBody(raw, contentType, expectedId) {
  if (!raw) return null;
  if (contentType.includes("text/event-stream")) {
    const events = raw.split(/\r?\n\r?\n/);
    for (const event of events) {
      const data = event.split(/\r?\n/).filter(line => line.startsWith("data:"))
        .map(line => line.slice(5).trim()).join("\n");
      if (!data || data === "[DONE]") continue;
      try {
        const parsed = JSON.parse(data);
        if (parsed.id === expectedId) return parsed;
      } catch { /* Ignore non-JSON SSE frames. */ }
    }
    return null;
  }
  const parsed = JSON.parse(raw);
  if (Array.isArray(parsed)) return parsed.find(item => item?.id === expectedId) || null;
  return parsed?.id === expectedId ? parsed : null;
}

async function postMcp(endpoint, payload, sessionId, fetchImpl) {
  const headers = {
    accept: "application/json, text/event-stream",
    "content-type": "application/json",
  };
  headers["mcp-protocol-version"] = MCP_VERSION;
  if (sessionId) headers["mcp-session-id"] = sessionId;
  const response = await fetchImpl(endpoint, {
    method: "POST",
    headers,
    body: JSON.stringify(payload),
    redirect: "manual",
    signal: AbortSignal.timeout(15_000),
  });
  if (response.status === 202 || response.status === 204) {
    if (payload.method?.startsWith("notifications/")) return { sessionId: response.headers.get("mcp-session-id") || sessionId, message: null };
  }
  if (!response.ok) throw new Error("SwarmMemo MCP returned HTTP " + response.status);
  const length = Number(response.headers.get("content-length") || 0);
  if (length > MAX_MCP_BYTES) throw new Error("SwarmMemo MCP response exceeded size limit");
  const raw = await response.text();
  if (new TextEncoder().encode(raw).length > MAX_MCP_BYTES) throw new Error("SwarmMemo MCP response exceeded size limit");
  const message = parseMcpBody(raw, response.headers.get("content-type") || "", payload.id);
  if (!message) throw new Error("SwarmMemo MCP returned no matching JSON-RPC response");
  if (message.error) throw new Error("SwarmMemo MCP error " + String(message.error.code) + ": " + String(message.error.message || "unknown"));
  return { sessionId: response.headers.get("mcp-session-id") || sessionId, message };
}

function validateIdentityUrl(value) {
  if (typeof value !== "string" || value.length > 2048) throw new Error("SwarmMemo did not return an identity MCP URL");
  let parsed;
  try { parsed = new URL(value); } catch { throw new Error("SwarmMemo returned an invalid identity MCP URL"); }
  if (parsed.protocol !== "https:" || parsed.hostname !== "swarmmemo.com" ||
      !["/mcp", "/mcp/assistant", "/mcp/core"].includes(parsed.pathname) ||
      parsed.username || parsed.password || parsed.hash) {
    throw new Error("SwarmMemo returned an identity URL outside the approved HTTPS MCP origin");
  }
  return parsed;
}

function identityResult(toolResult) {
  if (toolResult?.isError) throw new Error("SwarmMemo create_identity tool reported an error");
  if (toolResult?.structuredContent && typeof toolResult.structuredContent === "object") return toolResult.structuredContent;
  for (const part of toolResult?.content || []) {
    if (typeof part?.text !== "string") continue;
    try { return JSON.parse(part.text); } catch { /* Try the next text block. */ }
  }
  throw new Error("SwarmMemo create_identity returned an unrecognized result");
}

export async function callSwarmMemoTool(endpoint, name, args = {}, fetchImpl = fetch) {
  const url = validateIdentityUrl(endpoint).toString();
  const init = await postMcp(url, {
    jsonrpc: "2.0", id: 1, method: "initialize",
    params: {
      protocolVersion: MCP_VERSION,
      capabilities: {},
      clientInfo: { name: "autonomous-ai-economy", version: "0.1.0" },
    },
  }, null, fetchImpl);
  const sessionId = init.sessionId;
  await postMcp(url, { jsonrpc: "2.0", method: "notifications/initialized" }, sessionId, fetchImpl);
  const called = await postMcp(url, {
    jsonrpc: "2.0", id: 2, method: "tools/call",
    params: { name, arguments: args },
  }, sessionId, fetchImpl);
  return called.message.result;
}

export async function listSwarmMemoTools(endpoint, fetchImpl = fetch) {
  const url = validateIdentityUrl(endpoint);
  url.searchParams.set("toolsets", "all");
  const endpointUrl = url.toString();
  const init = await postMcp(endpointUrl, {
    jsonrpc: "2.0", id: 1, method: "initialize",
    params: {
      protocolVersion: MCP_VERSION,
      capabilities: {},
      clientInfo: { name: "autonomous-ai-economy", version: "0.1.0" },
    },
  }, null, fetchImpl);
  await postMcp(endpointUrl, { jsonrpc: "2.0", method: "notifications/initialized" }, init.sessionId, fetchImpl);
  const listed = await postMcp(endpointUrl, { jsonrpc: "2.0", id: 2, method: "tools/list", params: {} }, init.sessionId, fetchImpl);
  return Array.isArray(listed.message.result?.tools) ? listed.message.result.tools : [];
}

export async function createHostedSwarmMemoIdentity(fetchImpl = fetch) {
  const init = await postMcp(MCP_ENDPOINT, {
    jsonrpc: "2.0", id: 1, method: "initialize",
    params: {
      protocolVersion: MCP_VERSION,
      capabilities: {},
      clientInfo: { name: "autonomous-ai-economy", version: "0.1.0" },
    },
  }, null, fetchImpl);
  await postMcp(MCP_ENDPOINT, { jsonrpc: "2.0", method: "notifications/initialized" }, init.sessionId, fetchImpl);
  const created = await postMcp(MCP_ENDPOINT, {
    jsonrpc: "2.0", id: 2, method: "tools/call",
    params: { name: "create_identity", arguments: {} },
  }, init.sessionId, fetchImpl);
  const data = identityResult(created.message.result);
  const mcpUrl = validateIdentityUrl(data.mcp_url || data.assistant_mcp_url);
  const recoveryCode = typeof data.recovery_code === "string" ? data.recovery_code : "";
  const fingerprint = typeof data.fingerprint === "string" ? data.fingerprint : "";
  if (!recoveryCode || !fingerprint) throw new Error("SwarmMemo identity response omitted recovery code or fingerprint");
  return {
    mcp_url: mcpUrl.toString(),
    recovery_code: recoveryCode,
    fingerprint,
    handle: typeof data.handle === "string" ? data.handle : null,
  };
}

const IDENTITY_AAD = new TextEncoder().encode("aae:swarmmemo:identity:v1");

function bytesToBase64(bytes) {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary);
}

function base64ToBytes(value) {
  const binary = atob(value);
  return Uint8Array.from(binary, char => char.charCodeAt(0));
}

async function identityEncryptionKey(secret, salt) {
  if (typeof secret !== "string" || secret.length < 32) {
    throw new Error("AAE_QUEUE_TOKEN must be configured with at least 32 characters to protect SwarmMemo identity credentials");
  }
  const material = await crypto.subtle.importKey("raw", new TextEncoder().encode(secret), "HKDF", false, ["deriveKey"]);
  return crypto.subtle.deriveKey(
    { name: "HKDF", hash: "SHA-256", salt, info: IDENTITY_AAD },
    material,
    { name: "AES-GCM", length: 256 },
    false,
    ["encrypt", "decrypt"],
  );
}

export async function encryptIdentityCredentials(secret, identity) {
  const salt = crypto.getRandomValues(new Uint8Array(16));
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const key = await identityEncryptionKey(secret, salt);
  const plaintext = new TextEncoder().encode(JSON.stringify({
    mcp_url: identity.mcp_url,
    recovery_code: identity.recovery_code,
  }));
  const encrypted = await crypto.subtle.encrypt(
    { name: "AES-GCM", iv, additionalData: IDENTITY_AAD },
    key,
    plaintext,
  );
  return {
    credentials_ciphertext: bytesToBase64(new Uint8Array(encrypted)),
    credentials_salt: bytesToBase64(salt),
    credentials_iv: bytesToBase64(iv),
  };
}

export async function decryptIdentityCredentials(secret, row) {
  if (!row?.credentials_ciphertext || !row?.credentials_salt || !row?.credentials_iv) {
    throw new Error("encrypted SwarmMemo identity credentials are unavailable");
  }
  const salt = base64ToBytes(row.credentials_salt);
  const iv = base64ToBytes(row.credentials_iv);
  const key = await identityEncryptionKey(secret, salt);
  const plaintext = await crypto.subtle.decrypt(
    { name: "AES-GCM", iv, additionalData: IDENTITY_AAD },
    key,
    base64ToBytes(row.credentials_ciphertext),
  );
  const data = JSON.parse(new TextDecoder().decode(plaintext));
  const mcpUrl = validateIdentityUrl(data.mcp_url);
  if (typeof data.recovery_code !== "string" || !data.recovery_code) {
    throw new Error("encrypted SwarmMemo recovery material is invalid");
  }
  return { mcp_url: mcpUrl.toString(), recovery_code: data.recovery_code };
}

export async function getStoredSwarmMemoIdentity(env) {
  const row = await env.DB.prepare(
    "SELECT state,fingerprint,handle,credentials_ciphertext,credentials_salt,credentials_iv FROM swarmmemo_identity_state WHERE id=1"
  ).first();
  if (!row || row.state !== "created") return { ready: false, state: row?.state || "not_created" };
  const credentials = await decryptIdentityCredentials(env.AAE_QUEUE_TOKEN, row);
  return {
    ready: true,
    fingerprint: row.fingerprint,
    handle: row.handle,
    mcp_url: credentials.mcp_url,
    recovery_code: credentials.recovery_code,
  };
}

export async function ensureHostedSwarmMemoIdentity(env, fetchImpl = fetch) {
  if (typeof env.AAE_QUEUE_TOKEN !== "string" || env.AAE_QUEUE_TOKEN.length < 32) return { ready: false, state: "missing_or_weak_encryption_secret" };
  const now = new Date().toISOString();
  const current = await env.DB.prepare(
    "SELECT state,fingerprint,handle,credentials_ciphertext,credentials_salt,credentials_iv FROM swarmmemo_identity_state WHERE id=1"
  ).first();
  if (current?.state === "created") {
    if (!current.credentials_ciphertext) return { ready: false, state: "created_without_encrypted_credentials" };
    const credentials = await decryptIdentityCredentials(env.AAE_QUEUE_TOKEN, current);
    return { ready: true, state: "created", fingerprint: current.fingerprint, handle: current.handle, mcp_url: credentials.mcp_url };
  }
  if (current) return { ready: false, state: current.state || "unknown" };
  const reserved = await env.DB.prepare(
    "INSERT OR IGNORE INTO swarmmemo_identity_state (id,state,updated_at) VALUES (1,'creating',?)"
  ).bind(now).run();
  if (reserved.meta?.changes !== 1) return { ready: false, state: "bootstrap_race" };
  try {
    const identity = await createHostedSwarmMemoIdentity(fetchImpl);
    const encrypted = await encryptIdentityCredentials(env.AAE_QUEUE_TOKEN, identity);
    await env.DB.prepare(
      "UPDATE swarmmemo_identity_state SET state='created',fingerprint=?,handle=?,created_at=?,credentials_ciphertext=?,credentials_salt=?,credentials_iv=?,updated_at=? WHERE id=1 AND state='creating'"
    ).bind(identity.fingerprint, identity.handle, now, encrypted.credentials_ciphertext,
      encrypted.credentials_salt, encrypted.credentials_iv, new Date().toISOString()).run();
    return { ready: true, state: "created", fingerprint: identity.fingerprint, handle: identity.handle, mcp_url: identity.mcp_url };
  } catch (error) {
    await env.DB.prepare(
      "UPDATE swarmmemo_identity_state SET state='uncertain',updated_at=? WHERE id=1 AND state='creating'"
    ).bind(new Date().toISOString()).run();
    return { ready: false, state: "uncertain", error: String(error?.message || "identity bootstrap failed").slice(0, 300) };
  }
}

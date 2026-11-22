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
  const hostedTokenPath = /^\/mcp\/t\/[A-Za-z0-9_-]{16,512}$/.test(parsed.pathname);
  const approvedPath = ["/mcp", "/mcp/assistant", "/mcp/core"].includes(parsed.pathname) || hostedTokenPath;
  const queryEntries = [...parsed.searchParams.entries()];
  const approvedQuery = queryEntries.every(([key, item]) =>
    (key === "token" && /^[A-Za-z0-9_-]{16,512}$/.test(item)) ||
    (key === "toolsets" && item === "all")
  ) && new Set(queryEntries.map(([key]) => key)).size === queryEntries.length;
  const carriesIdentityToken = hostedTokenPath || /^[A-Za-z0-9_-]{16,512}$/.test(parsed.searchParams.get("token") || "");
  if (parsed.protocol !== "https:" || !["swarmmemo.com", "www.swarmmemo.com"].includes(parsed.hostname) ||
      !approvedPath || !approvedQuery || !carriesIdentityToken ||
      parsed.username || parsed.password || parsed.hash) {
    throw new Error("SwarmMemo returned an identity URL outside the approved HTTPS MCP origin or without a supported token location");
  }
  return parsed;
}

function findIdentityPayload(value, depth = 0) {
  if (!value || typeof value !== "object" || depth > 6) return null;
  if (typeof value.mcp_url === "string" || typeof value.assistant_mcp_url === "string") return value;
  for (const key of ["data", "result", "identity", "agent", "structuredContent", "output"]) {
    const found = findIdentityPayload(value[key], depth + 1);
    if (found) return found;
  }
  if (Array.isArray(value.content)) {
    for (const part of value.content) {
      if (typeof part?.text === "string") {
        try {
          const parsed = JSON.parse(part.text);
          const found = findIdentityPayload(parsed, depth + 1);
          if (found) return found;
        } catch { /* The server may return a human-readable one-time credential receipt. */ }
        const text = part.text;
        const url = text.match(/https:\/\/(?:www\.)?swarmmemo\.com\/(?:mcp(?:\/assistant|\/core)?(?:\/t\/[A-Za-z0-9_-]{16,512})?)(?:\?[^\s"'<>]*)?/i)?.[0];
        const recovery = text.match(/smr1_[A-Za-z0-9_-]{12,256}/)?.[0];
        const fingerprint = text.match(/(?:fingerprint|agent fingerprint)[^a-f0-9]*([a-f0-9]{64})/i)?.[1];
        if (url && recovery && fingerprint) {
          const handle = text.match(/(?:handle|name)[^A-Za-z0-9_-]*([A-Za-z0-9_-]{1,32})/i)?.[1] || null;
          return { mcp_url: url, recovery_code: recovery, fingerprint, handle };
        }
      }
    }
  }
  return null;
}

function identityResult(toolResult) {
  if (toolResult?.isError) throw new Error("SwarmMemo create_identity tool reported an error");
  const found = findIdentityPayload(toolResult?.structuredContent) || findIdentityPayload(toolResult);
  if (found) return found;
  throw new Error("SwarmMemo create_identity returned no recognizable identity URL, recovery code, and fingerprint");
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
    throw new Error("AAE_IDENTITY_ENCRYPTION_KEY must be configured with at least 32 characters to protect SwarmMemo identity credentials");
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
  const credentials = await decryptIdentityCredentials(env.AAE_IDENTITY_ENCRYPTION_KEY, row);
  return {
    ready: true,
    fingerprint: row.fingerprint,
    handle: row.handle,
    mcp_url: credentials.mcp_url,
    recovery_code: credentials.recovery_code,
  };
}

export async function ensureHostedSwarmMemoIdentity(env, fetchImpl = fetch) {
  const now = new Date().toISOString();
  if (typeof env.AAE_IDENTITY_ENCRYPTION_KEY !== "string" || env.AAE_IDENTITY_ENCRYPTION_KEY.length < 32) {
    await env.DB.prepare(
      "INSERT INTO swarmmemo_identity_state (id,state,updated_at,last_error) VALUES (1,'failed',?,?) ON CONFLICT(id) DO UPDATE SET state=CASE WHEN state='created' THEN state ELSE 'failed' END,last_error=CASE WHEN state='created' THEN last_error ELSE excluded.last_error END,updated_at=excluded.updated_at"
    ).bind(now, "missing_or_weak_encryption_secret:length=" + String(env.AAE_IDENTITY_ENCRYPTION_KEY?.length || 0)).run();
    return { ready: false, state: "missing_or_weak_encryption_secret" };
  }
  const current = await env.DB.prepare(
    "SELECT state,fingerprint,handle,credentials_ciphertext,credentials_salt,credentials_iv,last_error FROM swarmmemo_identity_state WHERE id=1"
  ).first();
  if (current?.state === "created") {
    if (!current.credentials_ciphertext) return { ready: false, state: "created_without_encrypted_credentials" };
    const credentials = await decryptIdentityCredentials(env.AAE_IDENTITY_ENCRYPTION_KEY, current);
    return { ready: true, state: "created", fingerprint: current.fingerprint, handle: current.handle, mcp_url: credentials.mcp_url };
  }
  const recoverableLostResponse = current?.state === "uncertain" &&
    [
      "SwarmMemo did not return an identity MCP URL",
      "SwarmMemo returned an identity URL outside the approved HTTPS MCP origin",
    ].includes(current.last_error) &&
    !current.fingerprint && !current.credentials_ciphertext;
  if (current && current.state !== "failed" && !recoverableLostResponse) {
    return { ready: false, state: current.state || "unknown" };
  }
  const reserved = current?.state === "failed" || recoverableLostResponse
    ? await env.DB.prepare(
        "UPDATE swarmmemo_identity_state SET state='creating',last_error=NULL,updated_at=? WHERE id=1 AND state=? AND fingerprint IS NULL AND credentials_ciphertext IS NULL"
      ).bind(now, current.state).run()
    : await env.DB.prepare(
        "INSERT OR IGNORE INTO swarmmemo_identity_state (id,state,updated_at) VALUES (1,'creating',?)"
      ).bind(now).run();
  if (reserved.meta?.changes !== 1) return { ready: false, state: "bootstrap_race" };
  try {
    const identity = await createHostedSwarmMemoIdentity(fetchImpl);
    const encrypted = await encryptIdentityCredentials(env.AAE_IDENTITY_ENCRYPTION_KEY, identity);
    await env.DB.prepare(
      "UPDATE swarmmemo_identity_state SET state='created',fingerprint=?,handle=?,created_at=?,credentials_ciphertext=?,credentials_salt=?,credentials_iv=?,last_error=NULL,updated_at=? WHERE id=1 AND state='creating'"
    ).bind(identity.fingerprint, identity.handle, now, encrypted.credentials_ciphertext,
      encrypted.credentials_salt, encrypted.credentials_iv, new Date().toISOString()).run();
    return { ready: true, state: "created", fingerprint: identity.fingerprint, handle: identity.handle, mcp_url: identity.mcp_url };
  } catch (error) {
    await env.DB.prepare(
      "UPDATE swarmmemo_identity_state SET state='uncertain',last_error=?,updated_at=? WHERE id=1 AND state='creating'"
    ).bind(String(error?.message || "identity bootstrap failed").slice(0, 300), new Date().toISOString()).run();
    return { ready: false, state: "uncertain", error: String(error?.message || "identity bootstrap failed").slice(0, 300) };
  }
}

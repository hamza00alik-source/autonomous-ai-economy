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

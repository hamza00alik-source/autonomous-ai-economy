import test from "node:test";
import assert from "node:assert/strict";
import { callSwarmMemoTool, createHostedSwarmMemoIdentity, listSwarmMemoTools } from "../src/swarmmemo_mcp.js";

function mockFetch(responses, seen) {
  return async (url, options) => {
    seen.push({ url, options, body: options.body ? JSON.parse(options.body) : null });
    const next = responses.shift();
    if (!next) throw new Error("unexpected MCP request");
    return new Response(next.body === undefined ? "" : JSON.stringify(next.body), {
      status: next.status || 200,
      headers: {
        "content-type": "application/json",
        ...(next.session ? { "mcp-session-id": next.session } : {}),
      },
    });
  };
}

test("creates a hosted identity through the full MCP endpoint", async () => {
  const seen = [];
  const fetchImpl = mockFetch([
    { session: "session-1", body: { jsonrpc: "2.0", id: 1, result: { protocolVersion: "2025-03-26", capabilities: {} } } },
    { status: 202, session: "session-1" },
    { session: "session-1", body: { jsonrpc: "2.0", id: 2, result: { content: [{ type: "text", text: JSON.stringify({
      mcp_url: "https://swarmmemo.com/mcp?identity=opaque",
      recovery_code: "smr1-test-recovery",
      fingerprint: "fingerprint-test",
      handle: "aae-test",
    }) }] } } },
  ], seen);
  const identity = await createHostedSwarmMemoIdentity(fetchImpl);
  assert.equal(identity.mcp_url, "https://swarmmemo.com/mcp?identity=opaque");
  assert.equal(identity.recovery_code, "smr1-test-recovery");
  assert.equal(identity.fingerprint, "fingerprint-test");
  assert.equal(seen[0].body.method, "initialize");
  assert.equal(seen[2].body.params.name, "create_identity");
  assert.equal(seen[2].url, "https://swarmmemo.com/mcp?toolsets=all");
});

test("calls a tool on a hosted identity URL with session continuity", async () => {
  const seen = [];
  const fetchImpl = mockFetch([
    { session: "session-2", body: { jsonrpc: "2.0", id: 1, result: {} } },
    { status: 202, session: "session-2" },
    { session: "session-2", body: { jsonrpc: "2.0", id: 2, result: { content: [{ type: "text", text: "ok" }] } } },
  ], seen);
  const result = await callSwarmMemoTool("https://swarmmemo.com/mcp?identity=opaque", "find_work", { kind: "rewarded" }, fetchImpl);
  assert.equal(result.content[0].text, "ok");
  assert.equal(seen[2].body.params.name, "find_work");
  assert.equal(seen[2].options.headers["mcp-session-id"], "session-2");
});

test("rejects identity URLs outside SwarmMemo HTTPS MCP origin", async () => {
  await assert.rejects(
    callSwarmMemoTool("https://evil.example/mcp?token=bad", "find_work", {}, async () => { throw new Error("must not fetch"); }),
    /approved HTTPS MCP origin/
  );
});

test("fails closed when identity creation omits recovery material", async () => {
  const seen = [];
  const fetchImpl = mockFetch([
    { session: "session-3", body: { jsonrpc: "2.0", id: 1, result: {} } },
    { status: 202, session: "session-3" },
    { session: "session-3", body: { jsonrpc: "2.0", id: 2, result: { content: [{ type: "text", text: JSON.stringify({
      mcp_url: "https://swarmmemo.com/mcp?identity=opaque",
      fingerprint: "fingerprint-test",
    }) }] } } },
  ], seen);
  await assert.rejects(createHostedSwarmMemoIdentity(fetchImpl), /omitted recovery code or fingerprint/);
});

test("lists paid-work tools on the identity MCP URL", async () => {
  const seen = [];
  const fetchImpl = mockFetch([
    { session: "session-4", body: { jsonrpc: "2.0", id: 1, result: {} } },
    { status: 202, session: "session-4" },
    { session: "session-4", body: { jsonrpc: "2.0", id: 2, result: { tools: [
      { name: "find_work" }, { name: "post_message" }, { name: "claim_work" },
    ] } } },
  ], seen);
  const tools = await listSwarmMemoTools("https://swarmmemo.com/mcp?identity=opaque", fetchImpl);
  assert.deepEqual(tools.map(tool => tool.name), ["find_work", "post_message", "claim_work"]);
  assert.equal(seen[2].body.method, "tools/list");
  assert.match(seen[0].url, /toolsets=all/);
});

test("preserves assistant_mcp_url identity response without losing recovery code", async () => {
  const seen = [];
  const fetchImpl = mockFetch([
    { session: "session-5", body: { jsonrpc: "2.0", id: 1, result: {} } },
    { status: 202, session: "session-5" },
    { session: "session-5", body: { jsonrpc: "2.0", id: 2, result: { content: [{ type: "text", text: JSON.stringify({
      assistant_mcp_url: "https://swarmmemo.com/mcp/assistant?identity=opaque",
      recovery_code: "smr1-recovery",
      fingerprint: "fingerprint-5",
    }) }] } } },
  ], seen);
  const identity = await createHostedSwarmMemoIdentity(fetchImpl);
  assert.equal(identity.mcp_url, "https://swarmmemo.com/mcp/assistant?identity=opaque");
  assert.equal(identity.recovery_code, "smr1-recovery");
});

test("encrypts hosted identity credentials and decrypts only with the AAE queue secret", async () => {
  const { encryptIdentityCredentials, decryptIdentityCredentials } = await import("../src/swarmmemo_mcp.js");
  const identity = {
    mcp_url: "https://swarmmemo.com/mcp?identity=private-token",
    recovery_code: "smr1-private-recovery-code",
  };
  const encrypted = await encryptIdentityCredentials("a-long-random-worker-token-that-is-not-public", identity);
  assert.ok(encrypted.credentials_ciphertext);
  assert.ok(encrypted.credentials_salt);
  assert.ok(encrypted.credentials_iv);
  assert.equal(JSON.stringify(encrypted).includes(identity.mcp_url), false);
  assert.equal(JSON.stringify(encrypted).includes(identity.recovery_code), false);
  const decrypted = await decryptIdentityCredentials("a-long-random-worker-token-that-is-not-public", encrypted);
  assert.deepEqual(decrypted, identity);
  await assert.rejects(
    decryptIdentityCredentials("a-different-long-random-worker-token", encrypted),
  );
});

test("rejects weak encryption secret and malformed identity credentials", async () => {
  const { encryptIdentityCredentials, decryptIdentityCredentials } = await import("../src/swarmmemo_mcp.js");
  await assert.rejects(
    encryptIdentityCredentials("short", { mcp_url: "https://swarmmemo.com/mcp", recovery_code: "x" }),
    /at least 32 characters/,
  );
  await assert.rejects(
    decryptIdentityCredentials("a-long-random-worker-token-that-is-not-public", {}),
    /credentials are unavailable/,
  );
});

test("does not create a remote identity when the encryption secret is weak", async () => {
  const { ensureHostedSwarmMemoIdentity } = await import("../src/swarmmemo_mcp.js");
  let fetchCalled = false;
  let savedError = null;
  const env = {
    AAE_QUEUE_TOKEN: "short",
    DB: {
      prepare(sql) {
        const statement = {
          bind(...values) { savedError = values[1]; return statement; },
          async run() { return { meta: { changes: 1 } }; },
        };
        return statement;
      },
    },
  };
  const result = await ensureHostedSwarmMemoIdentity(
    env,
    async () => { fetchCalled = true; throw new Error("must not create identity"); },
  );
  assert.equal(result.ready, false);
  assert.equal(result.state, "missing_or_weak_encryption_secret");
  assert.equal(savedError, "missing_or_weak_encryption_secret");
  assert.equal(fetchCalled, false);
});

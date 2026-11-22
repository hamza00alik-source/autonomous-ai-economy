const MAX_REQUEST_BYTES = 200_000;
const MAX_URLS = 8;
const MAX_SOURCE_BYTES = 1_000_000;
const MAX_TEXT_CHARS = 30_000;
const POLICY_ATTESTATION = "aae-source-egress-v1";
const ALLOWED_TYPES = new Set(["text/html", "application/xhtml+xml", "text/plain"]);

function json(data, status = 200) {
  return new Response(JSON.stringify(data), { status, headers: {
    "content-type": "application/json; charset=utf-8", "cache-control": "no-store",
  }});
}
function equalSecret(left, right) {
  if (typeof left !== "string" || typeof right !== "string" || !left || !right) return false;
  let diff = left.length ^ right.length;
  for (let i = 0; i < Math.max(left.length, right.length); i++) {
    diff |= (left.charCodeAt(i % left.length) || 0) ^ (right.charCodeAt(i % right.length) || 0);
  }
  return diff === 0;
}
function allowedHosts(env) {
  return new Set(String(env.ALLOWED_SOURCE_HOSTS || "").split(",")
    .map(value => value.trim().toLowerCase().replace(/\.$/, "")).filter(Boolean));
}
function isIpLiteral(host) {
  return host.startsWith("[") || /^\d+(?:\.\d+){0,3}$/.test(host) ||
    (/^[0-9a-f:]+$/i.test(host) && host.includes(":"));
}
function validateUrl(raw, hosts) {
  if (typeof raw !== "string" || raw.length > 2048 || /[\u0000-\u0020\\]/.test(raw)) throw new Error("malformed source URL");
  let url;
  try { url = new URL(raw); } catch { throw new Error("malformed source URL"); }
  const host = url.hostname.toLowerCase().replace(/\.$/, "");
  if (url.protocol !== "https:" || url.username || url.password || (url.port && url.port !== "443") ||
      isIpLiteral(host) || !host.includes(".") ||
      /(?:^|\.)(localhost|local|internal|onion|test|invalid)$/i.test(host) || !hosts.has(host)) {
    throw new Error("source host is not explicitly allowlisted");
  }
  url.hash = "";
  return url;
}
async function readBounded(response, limit) {
  if (!response.body) return new Uint8Array();
  const reader = response.body.getReader();
  const chunks = [];
  let total = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      total += value.byteLength;
      if (total > limit) {
        await reader.cancel("source body exceeds limit");
        throw new Error("source response exceeds 1 MB limit");
      }
      chunks.push(value);
    }
  } finally { reader.releaseLock(); }
  const bytes = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
  return bytes;
}
function visibleText(content, contentType) {
  let text = content;
  if (contentType !== "text/plain") {
    text = text.replace(/<(script|style|noscript|template|svg)[^>]*>[\s\S]*?<\/\1\s*>/gi, " ");
    text = text.replace(/<!--[\s\S]*?-->/g, " ");
    text = text.replace(/<br\s*\/?>|<\/(?:p|div|li|h[1-6]|article|section)>/gi, "\n");
    text = text.replace(/<[^>]+>/g, " ");
  }
  return text.replace(/&nbsp;/gi, " ").replace(/&amp;/gi, "&").replace(/&lt;/gi, "<")
    .replace(/&gt;/gi, ">").replace(/&quot;/gi, '"').replace(/&#39;|&apos;/gi, "'")
    .replace(/\s+/g, " ").trim().slice(0, MAX_TEXT_CHARS);
}
function titleFrom(content) {
  return (content.match(/<title[^>]*>([\s\S]*?)<\/title>/i)?.[1] ||
    content.match(/<h1[^>]*>([\s\S]*?)<\/h1>/i)?.[1] || "Untitled source")
    .replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim().slice(0, 300) || "Untitled source";
}
function exactExcerpt(sourceText, draft) {
  for (const sentence of sourceText.split(/(?<=[.!?])\s+/)) {
    const candidate = sentence.trim();
    if (candidate.length >= 30 && candidate.length <= 800 && draft.includes(candidate)) return candidate;
  }
  const words = sourceText.split(/\s+/);
  for (const width of [12, 8, 6]) {
    for (let start = 0; start + width <= words.length; start++) {
      const candidate = words.slice(start, start + width).join(" ");
      if (candidate.length >= 30 && candidate.length <= 800 && draft.includes(candidate)) return candidate;
    }
  }
  return "";
}
async function verifyOne(url, draft, env) {
  // No global fetch fallback: all source traffic must traverse the VPC/Gateway binding.
  const response = await env.EGRESS.fetch(url.href, {
    method: "GET", redirect: "manual",
    headers: { "user-agent": "AutonomousAIEconomy-SourceVerifier/1.0",
      "accept": "text/html, application/xhtml+xml, text/plain" },
    signal: AbortSignal.timeout(8_000),
  });
  if (response.status >= 300 && response.status < 400) {
    await response.body?.cancel();
    throw new Error("redirects are disabled; submit the canonical source URL");
  }
  if (response.status !== 200) {
    await response.body?.cancel();
    throw new Error("source returned HTTP " + response.status);
  }
  const contentType = (response.headers.get("content-type") || "").split(";", 1)[0].trim().toLowerCase();
  if (!ALLOWED_TYPES.has(contentType)) {
    await response.body?.cancel();
    throw new Error("unsupported source content type");
  }
  const declaredLength = Number(response.headers.get("content-length") || 0);
  if (declaredLength > MAX_SOURCE_BYTES) {
    await response.body?.cancel();
    throw new Error("source response exceeds 1 MB limit");
  }
  const body = await readBounded(response, MAX_SOURCE_BYTES);
  const raw = new TextDecoder("utf-8", { fatal: false }).decode(body);
  const text = visibleText(raw, contentType);
  const excerpt = exactExcerpt(text, draft);
  const digest = await crypto.subtle.digest("SHA-256", body);
  const contentSha256 = [...new Uint8Array(digest)].map(byte => byte.toString(16).padStart(2, "0")).join("");
  return {
    requestedUrl: url.href, finalUrl: url.href, httpStatus: 200,
    title: contentType === "text/plain" ? "Plain-text source" : titleFrom(raw),
    contentType, contentSha256, fetchedAt: new Date().toISOString(),
    sourceExcerpt: excerpt, draftExcerpt: excerpt, excerptMatched: Boolean(excerpt),
    verificationStatus: "retrieved_unverified", supportsClaims: false,
  };
}
export default {
  async fetch(request, env) {
    const pathname = new URL(request.url).pathname;
    if (pathname !== "/healthz" && pathname !== "/v1/verify") return json({ error: "not found" }, 404);
    if (!equalSecret(request.headers.get("x-aae-source-verifier-token"), env.INTERNAL_SERVICE_TOKEN)) {
      return json({ error: "unauthorized" }, 401);
    }
    const configured = !!env.EGRESS && typeof env.EGRESS.fetch === "function" &&
      env.EGRESS_POLICY_ATTESTATION === POLICY_ATTESTATION &&
      !!env.INTERNAL_SERVICE_TOKEN && !!allowedHosts(env).size;
    if (pathname === "/healthz") return configured
      ? json({ ok: true, mode: "vpc_gateway_egress_configured" })
      : json({ ok: false, error: "source verifier egress is not configured" }, 503);
    if (request.method !== "POST") return json({ error: "method not allowed" }, 405);
    if (!configured) return json({ error: "source verifier egress is not configured; refusing outbound access" }, 503);
    const declaredLength = Number(request.headers.get("content-length") || 0);
    if (declaredLength > MAX_REQUEST_BYTES) return json({ error: "request too large" }, 413);
    let raw;
    try { raw = new TextDecoder().decode(await readBounded(request, MAX_REQUEST_BYTES)); }
    catch (error) { return json({ error: String(error.message || "request body too large").slice(0, 120) }, 413); }
    let payload;
    try { payload = JSON.parse(raw); } catch { return json({ error: "invalid JSON" }, 400); }
    if (payload?.protocolVersion !== 1 || !Array.isArray(payload.urls) ||
        payload.urls.length < 1 || payload.urls.length > MAX_URLS ||
        typeof payload.draft !== "string" || payload.draft.length > 12_000) {
      return json({ error: "invalid verification request" }, 400);
    }
    const hosts = allowedHosts(env);
    if (!hosts.size) return json({ error: "no source host allowlist configured" }, 503);
    let urls;
    try {
      urls = [...new Set(payload.urls.map(value => validateUrl(value, hosts).href))];
      if (urls.length !== payload.urls.length) return json({ error: "duplicate or normalized duplicate URLs" }, 400);
    } catch (error) {
      return json({ error: String(error.message || "invalid URL").slice(0, 160) }, 400);
    }
    const fetched = await Promise.allSettled(urls.map(value => verifyOne(new URL(value), payload.draft, env)));
    const failed = fetched.find(item => item.status === "rejected");
    if (failed) {
      return json({ protocolVersion: 1, status: "failed", results: [],
        error: String(failed.reason?.message || "source retrieval failed").slice(0, 200) }, 502);
    }
    const results = fetched.map(item => item.value);
    return json({
      protocolVersion: 1, status: "retrieved_unverified", retrievalVerified: true, results,
      notice: "This confirms retrieval, integrity hash and exact excerpt matching only; it does not attest claim support or factual correctness.",
    });
  },
};

const MAX_URLS = 8;
const MAX_DRAFT_CHARS = 12000;
const MAX_RESPONSE_BYTES = 64000;
const RESEARCH_PATTERN = /\b(research|investigate|fact[- ]check|market analysis|compare|comparison|cite|citations|sources)\b/i;
const URL_PATTERN = /https?:\/\/[^\s)\]}>,\"']+/gi;

function extractUrls(text) {
  return [...new Set([...String(text || "").matchAll(new RegExp(URL_PATTERN.source, "gi"))]
    .map(match => match[0].replace(/[.,;:!?]+$/, "")))];
}

function canonicalUrl(value) {
  try {
    const url = new URL(value);
    if (!["https:", "http:"].includes(url.protocol) || !url.hostname.includes(".") ||
        url.username || url.password || url.port && !["80", "443"].includes(url.port)) return null;
    return url.href;
  } catch {
    return null;
  }
}

function isPublicHostname(hostname) {
  const host = String(hostname || "").toLowerCase().replace(/\.$/, "");
  const labelsValid = host.split(".").every(label =>
    label.length > 0 && label.length <= 63 &&
    /^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$/.test(label));
  const blockedSuffix = /(?:^|\.)(localhost|local|internal|onion)$/i.test(host);
  const ipLiteral = host.startsWith("[") || /^\d+(?:\.\d+)*$/.test(host);
  return labelsValid && !blockedSuffix && !ipLiteral;
}

function validateUrlList(urls) {
  const normalized = [];
  for (const raw of urls) {
    const value = canonicalUrl(raw);
    if (!value) throw new Error('invalid source URL');
    const parsed = new URL(value);
    if (parsed.protocol !== "https:" || parsed.port || !isPublicHostname(parsed.hostname)) {
      throw new Error('source URL host is not allowed');
    }
    normalized.push(value);
  }
  return [...new Set(normalized)];
}
function validEvidence(item, draft, requestedUrl) {
  if (!item || typeof item !== "object" || item.requestedUrl !== requestedUrl ||
      item.httpStatus !== 200 || item.supportsClaims !== true ||
      typeof item.title !== "string" || !item.title.trim() || item.title.length > 300 ||
      typeof item.finalUrl !== "string" || !canonicalUrl(item.finalUrl) ||
      (() => { const finalUrl = new URL(item.finalUrl); return finalUrl.protocol !== "https:" || Boolean(finalUrl.port) || !isPublicHostname(finalUrl.hostname); })() ||
      typeof item.contentSha256 !== "string" || !/^[a-f0-9]{64}$/i.test(item.contentSha256) ||
      typeof item.fetchedAt !== "string" || !Number.isFinite(Date.parse(item.fetchedAt)) ||
      typeof item.sourceExcerpt !== "string" || item.sourceExcerpt.trim().length < 30 || item.sourceExcerpt.length > 800 ||
      typeof item.draftExcerpt !== "string" || item.draftExcerpt.trim().length < 15 || item.draftExcerpt.length > 800) return false;
  return draft.includes(item.draftExcerpt);
}

/**
 * Calls only a configured Cloudflare Service Binding. The verifier service owns
 * outbound fetching and must enforce SSRF, redirect, DNS/IP, byte, and timeout
 * protections. No user-controlled URL is fetched by this worker.
 */
export async function verifyResearchSources(env, task, draft) {
  const brief = [task?.title, task?.description].filter(value => typeof value === "string").join("\n");
  if (!RESEARCH_PATTERN.test(brief)) return { status: "not_required", verified: false, results: [], blockers: [] };

  let urls;
  try { urls = validateUrlList(extractUrls(draft)); } catch (error) {
    return { status: 'failed', verified: false, results: [], blockers: ['invalid_source_urls'], error: String(error.message).slice(0, 160) };
  }
  if (!urls.length) return { status: "failed", verified: false, results: [], blockers: ["research_sources_missing"] };
  if (urls.length > MAX_URLS) return { status: "failed", verified: false, results: [], blockers: ["too_many_research_sources"] };
  if (!env?.SOURCE_VERIFIER || typeof env.SOURCE_VERIFIER.fetch !== "function") {
    return { status: "unavailable", verified: false, results: [], blockers: ["source_verifier_unavailable"] };
  }

  try {
    const response = await env.SOURCE_VERIFIER.fetch("https://source-verifier.internal/v1/verify", {
      method: "POST",
      headers: { "content-type": "application/json", "accept": "application/json" },
      body: JSON.stringify({
        protocolVersion: 1,
        urls,
        task: { title: String(task?.title || "").slice(0, 1000), description: String(task?.description || "").slice(0, 8000) },
        draft: String(draft).slice(0, MAX_DRAFT_CHARS),
        limits: { maxUrls: MAX_URLS, maxResponseBytes: 1000000, timeoutMs: 8000, redirects: 3 },
      }),
      signal: AbortSignal.timeout(10000),
    });
    const declaredLength = Number(response.headers.get("content-length") || 0);
    if (declaredLength > MAX_RESPONSE_BYTES) throw new Error("verifier response too large");
    const raw = await response.text();
    if (new TextEncoder().encode(raw).byteLength > MAX_RESPONSE_BYTES) throw new Error("verifier response too large");
    if (!response.ok) throw new Error("verifier service returned " + response.status);
    const payload = JSON.parse(raw);
    if (payload?.protocolVersion !== 1 || payload?.status !== "verified" ||
        !Array.isArray(payload.results) || payload.results.length !== urls.length) {
      throw new Error("verifier response schema mismatch");
    }
    const byUrl = new Map(payload.results.map(item => [item?.requestedUrl, item]));
    const results = urls.map(url => byUrl.get(url));
    if (results.some(item => !validEvidence(item, draft, item?.requestedUrl)) ||
        urls.some(url => !byUrl.has(url))) throw new Error("verifier evidence failed validation");
    return { status: "verified", verified: true, results, blockers: [] };
  } catch (error) {
    return {
      status: "failed",
      verified: false,
      results: [],
      blockers: ["source_verification_failed"],
      error: String(error?.message || "source verification failed").slice(0, 240),
    };
  }
}

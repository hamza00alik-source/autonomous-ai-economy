const MAX_URL_LENGTH = 2048;

export function validateBrowserTarget(value) {
  if (typeof value !== "string" || value.length > MAX_URL_LENGTH) {
    throw new Error("A valid HTTPS URL is required");
  }
  let target;
  try { target = new URL(value); } catch { throw new Error("Invalid URL"); }
  const host = target.hostname.toLowerCase();
  const blockedHost = host === "localhost" || host.endsWith(".localhost") ||
    host.endsWith(".local") || host.endsWith(".internal") ||
    host === "metadata.google.internal" || /^169\\.254\\./.test(host) ||
    /^127\./.test(host) || /^10\./.test(host) ||
    /^192\.168\./.test(host) || /^172\.(1[6-9]|2\d|3[01])\./.test(host) ||
    host === "0.0.0.0" || host === "::1" || host === "[::1]" || host.startsWith("[fc") || host.startsWith("[fd");
  if (target.protocol !== "https:" || blockedHost || target.username || target.password ||
      target.port || target.hash) {
    throw new Error("Browser access is limited to public HTTPS URLs without credentials or custom ports");
  }
  return target;
}

export async function browserMarkdown(request, env) {
  let target;
  try {
    target = validateBrowserTarget(new URL(request.url).searchParams.get("url"));
  } catch (error) {
    return new Response(JSON.stringify({ error: String(error?.message || "Invalid URL") }), {
      status: 400, headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" },
    });
  }
  if (!env.BROWSER || typeof env.BROWSER.quickAction !== "function") {
    return new Response(JSON.stringify({ error: "Browser Run binding is unavailable" }), {
      status: 503, headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" },
    });
  }
  try {
    const response = await env.BROWSER.quickAction("markdown", {
      url: target.toString(),
      gotoOptions: { waitUntil: "domcontentloaded", timeout: 30000 },
    });
    const payload = await response.json();
    if (!response.ok || payload?.success === false) {
      return new Response(JSON.stringify({ error: "Browser extraction failed" }), {
        status: 502, headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" },
      });
    }
    return new Response(JSON.stringify({
      url: target.toString(),
      markdown: String(payload?.result || "").slice(0, 30000),
      browser_ms_used: Number(response.headers.get("X-Browser-Ms-Used") || 0),
      mode: "read_only",
    }), {
      status: 200, headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" },
    });
  } catch {
    return new Response(JSON.stringify({ error: "Browser Run request failed or its free daily allowance is unavailable" }), {
      status: 502, headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" },
    });
  }
}

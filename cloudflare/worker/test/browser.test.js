import test from "node:test";
import assert from "node:assert/strict";
import { browserMarkdown, validateBrowserTarget } from "../src/browser.js";

test("accepts public HTTPS targets", () => {
  assert.equal(validateBrowserTarget("https://example.com/path").hostname, "example.com");
});

test("rejects local, private, insecure, and credentialed targets", () => {
  for (const url of [
    "http://example.com",
    "https://localhost/",
    "https://127.0.0.1/",
    "https://192.168.1.2/",
    "https://169.254.169.254/",
    "https://[::1]/",
    "https://user:pass@example.com/",
    "https://example.com:8443/",
  ]) assert.throws(() => validateBrowserTarget(url));
});

test("returns rendered markdown without exposing browser credentials", async () => {
  const response = await browserMarkdown(
    new Request("https://worker.test/v1/browser/markdown?url=https%3A%2F%2Fexample.com"),
    { BROWSER: { quickAction: async () => new Response(JSON.stringify({success:true,result:"# Hello"}), {
      headers: {"content-type":"application/json","X-Browser-Ms-Used":"1234"}
    }) } }
  );
  assert.equal(response.status, 200);
  const result = await response.json();
  assert.equal(result.markdown, "# Hello");
  assert.equal(result.browser_ms_used, 1234);
  assert.equal(result.mode, "read_only");
});

test("fails closed when browser binding is unavailable", async () => {
  const response = await browserMarkdown(
    new Request("https://worker.test/v1/browser/markdown?url=https%3A%2F%2Fexample.com"),
    {}
  );
  assert.equal(response.status, 503);
});

import { cloudflareTest } from "@cloudflare/vitest-plugin";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [
    cloudflareTest({
      // Use a local-only config: the production Workers AI binding requires
      // a Cloudflare API token and is irrelevant to Durable Object persistence tests.
      wrangler: { configPath: "./wrangler.test.toml" },
    }),
  ],
  test: {
    include: ["test/*.workers.spec.js"],
    testTimeout: 30_000,
    hookTimeout: 30_000,
  },
});

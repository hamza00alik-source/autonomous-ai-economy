import { AgentKeyVaultCore } from "./agent_key_vault_core.js";

/**
 * Internal Durable Object adapter. The Worker reaches this object only through
 * its binding; no public Worker route exposes this fetch handler.
 */
export class AgentKeyVault {
  constructor(ctx, env) {
    this.ctx = ctx;
    this.env = env;
    this.vault = new AgentKeyVaultCore(ctx, env);
  }

  async fetch(request) {
    if (request.method !== "POST") {
      return new Response("Method not allowed", { status: 405 });
    }
    let input;
    try {
      input = await request.json();
    } catch {
      return Response.json({ error: "invalid JSON" }, { status: 400 });
    }

    try {
      let result;
      switch (input?.operation) {
        case "ensure_identity":
          result = await this.vault.ensureIdentity(input.agent_id);
          break;
        case "create_enrollment_proof":
          result = await this.vault.createEnrollmentProof(input.agent_id);
          break;
        case "sign_invoice_request":
          result = await this.vault.signInvoiceRequest(input.args);
          break;
        default:
          return Response.json({ error: "unsupported vault operation" }, { status: 400 });
      }
      return Response.json({ result }, {
        headers: { "cache-control": "no-store" },
      });
    } catch {
      // Do not leak key or storage internals through the object boundary.
      return Response.json({ error: "vault operation rejected" }, { status: 400 });
    }
  }
}

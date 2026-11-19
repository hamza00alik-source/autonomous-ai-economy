import { DurableObject } from "cloudflare:workers";
import { AgentKeyVaultCore } from "./agent_key_vault_core.js";

/** Cloudflare Durable Object adapter: one persistent vault per agent identity. */
export class AgentKeyVault extends DurableObject {
  constructor(ctx, env) {
    super(ctx, env);
    this.vault = new AgentKeyVaultCore(ctx, env);
  }

  ensureIdentity(agentId) {
    return this.vault.ensureIdentity(agentId);
  }

  createEnrollmentProof(agentId) {
    return this.vault.createEnrollmentProof(agentId);
  }

  signInvoiceRequest(args) {
    return this.vault.signInvoiceRequest(args);
  }
}

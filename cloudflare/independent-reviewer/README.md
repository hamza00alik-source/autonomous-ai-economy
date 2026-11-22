## AAE Independent Reviewer

This private Worker calls Google's Gemini API as a genuinely separate model provider. The specialist is Cloudflare Workers AI; the independent review is reported as independent only when the response has provider=google, independent=true and sameProvider=false. Same-model review is never described as independent.

It fails closed unless the VPC EGRESS binding, Gateway-policy attestation, GEMINI_API_KEY and INTERNAL_REVIEW_TOKEN are all configured. The VPC network must route through Cloudflare Gateway. Configure DNS/HTTP allow rules only for generativelanguage.googleapis.com over HTTPS and Network deny rules for private/special-use ranges. The code uses only env.EGRESS.fetch, fixed Google API host, disabled redirects, bounded request/response sizes and timeouts.

Secrets: GEMINI_API_KEY, INTERNAL_REVIEW_TOKEN, EGRESS_POLICY_ATTESTATION (value aae-review-egress-v1 only after Gateway controls are verified). Variable: GEMINI_MODEL (default gemini-3.8-flash). Google API calls may incur charges under the account's current quota and plan. Do not configure the key or activate this service until provider use and cost have explicit owner approval. Workers VPC is beta and requires an active Tunnel, Mesh node or WAN on-ramp.

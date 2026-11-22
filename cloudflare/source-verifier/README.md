# AAE Source Verifier

This service is not deploy-ready by default. It refuses outbound requests unless
an EGRESS Workers VPC binding, a Gateway-policy attestation secret, an exact
source-host allowlist, and an internal service token are all configured.

## Egress architecture

The service never uses global fetch for user-supplied source URLs. It uses only
env.EGRESS.fetch through a Workers VPC Network binding (cf1:network). Cloudflare
documents that public-Internet traffic from Workers VPC passes through Cloudflare
Gateway and is subject to DNS, HTTP and Network policies and logging. Workers VPC
is currently beta and free on Workers plans. A Tunnel, Mesh node or WAN on-ramp
is required only for private destinations, not public Internet egress.

Before setting EGRESS_POLICY_ATTESTATION to aae-source-egress-v1, configure
Gateway policies for this Worker/network:

1. DNS: allow only the exact approved source hostnames; deny other DNS lookups.
2. HTTP: allow HTTPS only to the exact approved hostnames; deny all other hosts.
3. Network: deny all non-global/special-use IPv4 and IPv6 ranges, including
   loopback, RFC1918, link-local, CGNAT, multicast, documentation, benchmark,
   IPv4-mapped IPv6, unique-local IPv6 and IPv6 link-local.
4. Deny IP-literal destinations and non-443 outbound ports.
5. Exclude this VPC traffic from unrelated Gateway Forward policies that would
   prevent VPC egress.
6. Confirm Gateway logs show the expected host and public destination IP and
   deny reserved/private destinations.
7. Perform controlled DNS-rebinding tests and verify the private destination
   is blocked on the actual connection path.

The code also enforces exact hostname allowlisting, HTTPS, no credentials,
no redirects, bounded time/body size, allowed content types and strict schema.
Redirects are rejected rather than followed.

The attestation is an operator acknowledgement, not cryptographic proof of
Gateway configuration. Until the policies and live rebinding tests are verified,
do not set the attestation secret or bind this service into production. The
parent AAE Worker must use a service binding and matching SOURCE_VERIFIER_TOKEN.

## Secrets and variables

Secrets: INTERNAL_SERVICE_TOKEN and EGRESS_POLICY_ATTESTATION. Set the latter
only after completing the Gateway policy checklist. Variable:
ALLOWED_SOURCE_HOSTS is a comma-separated list of exact approved hostnames.

## Evidence semantics

A successful response is retrieved_unverified. It confirms a 200 response,
SHA-256 integrity hash and (when possible) an exact excerpt also present in the
draft. It does not establish source trust, semantic relevance or claim support.

The parent Worker also needs a SOURCE_VERIFIER service binding and the SOURCE_VERIFIER_TOKEN secret. Set that secret to the same value as this Worker's INTERNAL_SERVICE_TOKEN. No token value belongs in source control.

# Optional AI model runtime

## Status

Implemented in `src/economy/ai_runtime.py` and exposed as `economy-ai`.

- Provider: Cloudflare Workers AI REST API.
- Fixed model allowlist: `@cf/zai-org/glm-4.7-flash`.
- Free-plan-first: local daily reservation cap of 6,500 estimated neurons.
- Prompt limit: 8,000 characters across messages.
- Output limit: 512 tokens.
- Credentials: `CLOUDFLARE_ACCOUNT_ID` and `CLOUDFLARE_API_TOKEN` environment variables.
- Network calls: only explicit `economy-ai invoke`; status and CI tests do not call the provider.
- No tool calls, shell access, browser actions, publishing, customer messaging, or financial actions.
- No model prompts or API tokens are written to the local budget database. Only a SHA-256 prompt digest, estimated reservation, model, request status and timestamps are stored.
- Failed/ambiguous requests keep their reservation; no automatic retries.

## Provider facts (checked 17 November 2026)

Cloudflare's pricing documentation says Workers AI includes 10,000 neurons per day at no charge on Workers Free, with usage above that requiring the paid plan. Its model availability changelog lists `@cf/zai-org/glm-4.7-flash` among models that remain available on Workers Free. Cloudflare's REST guide says a token needs Workers AI Read and Workers AI Edit permissions if created manually; prefer the provider's prefilled Workers AI token template.

Sources:
- https://developers.cloudflare.com/workers-ai/platform/pricing/
- https://developers.cloudflare.com/changelog/post/2026-07-28-models-require-workers-paid/
- https://developers.cloudflare.com/workers-ai/get-started/rest-api/

The 6,500-neuron local cap uses a conservative estimate based on published per-token rates and a safety multiplier. It is not exact provider metering. The Cloudflare dashboard remains authoritative; the provider may reject requests earlier because of account limits or quota enforcement.

## Configure

```bash
export CLOUDFLARE_ACCOUNT_ID="your-account-id"
export CLOUDFLARE_API_TOKEN="your-workers-ai-token"
economy-ai status
```

The status command does not make a network request and does not reveal secrets.

To run one explicit test:

```bash
printf 'Return a one-sentence greeting.' > prompt.txt
economy-ai invoke --prompt-file ./prompt.txt
```

Never commit credentials, paste them into chat, or store them in the repository. If using a hosted runtime later, put the token in the host's secret manager.

## Important boundary

This adapter is a model transport and budget guard, not yet a fully autonomous agent. The next engineering step is to connect the model to typed specialist-agent tasks, persist validated outputs, and let the existing policy/QA/approval system decide what can happen next. The model itself receives no direct tools or authority to publish, spend, contact buyers, or move money.

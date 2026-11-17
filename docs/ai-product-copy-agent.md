# AI product-copy agent

## What it does

`AIProductCopyAgent` uses the configured Cloudflare Workers AI adapter to draft a marketplace title, short description, full description, tags, AI disclosure, and a list of claims requiring verification. It consumes only supplied product facts.

The agent:
- treats the facts file as untrusted data rather than instructions;
- refuses missing or unexpected fact fields;
- rejects malformed JSON, missing product formats, omitted AI disclosure, and selected unsupported performance/endorsement claims;
- returns an unpublished draft only;
- has no publishing, browser, payment, customer-contact, shell, or arbitrary tool permissions.

## Run for MOBA Objective Props

Configure the Workers AI environment variables as described in `docs/ai-model-runtime.md`. For a one-off direct draft, run:

```bash
economy-ai draft-copy \
  --facts-file products/moba-objective-props/product-facts.json \
  --output data/moba-objective-props-listing-draft.json
```

The output file is created only if it does not already exist. Review all claims and technical details before using the copy. The model may produce invalid or unsupported text; validation is a guard, not proof of truth.

The command makes one model request and reserves estimated usage from the shared 6,500-neuron daily safety budget. It does not publish the listing or upload product files.\n\nFor queued autonomous execution, submit an idempotent task and let the supervisor process it:\n\n```bash\neconomy-ai queue-copy --facts-file products/moba-objective-props/product-facts.json\neconomy-supervisor --data-dir ./data\n```\n\nThe supervisor runs the AI task lane outside the no-network built-in sandbox. It only processes `ai-product-copy-agent` tasks when valid provider credentials are present. Tasks are single-attempt by default to avoid repeated model usage on failures. The result is stored in the task queue as an unpublished draft.

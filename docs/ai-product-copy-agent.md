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

Configure the Workers AI environment variables as described in `docs/ai-model-runtime.md`, then run:

```bash
economy-ai draft-copy \
  --facts-file products/moba-objective-props/product-facts.json \
  --output data/moba-objective-props-listing-draft.json
```

The output file is created only if it does not already exist. Review all claims and technical details before using the copy. The model may produce invalid or unsupported text; validation is a guard, not proof of truth.

The command makes one model request and reserves estimated usage from the shared 6,500-neuron daily safety budget. It does not publish the listing or upload product files.

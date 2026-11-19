# Approved Execution Worker

Status: draft implementation. It can run one built-in, allowlisted product producer after explicit approval. It is not an always-on cloud worker.

## Current registered capability

- Agent: `game-asset-builder`
- Specification: `{"kind":"moba_objective_props_v1"}`
- Output: deterministic ZIP containing five individual GLB models, a combined GLB, a Godot project, listing copy and a draft license.
- Execution code calls the existing Python producer directly. It does not invoke a shell, evaluate task text, run downloaded code, load plugins, or execute model-generated programs.

## Required gates

1. Fulfillment job must be in `in_progress`, after owner approval.
2. The enrolled agent ID and SHA-256 public-key fingerprint must pass the supplied identity verifier again.
3. A fresh owner approval token bound to the job ID and `execute` action must pass the supplied verifier.
4. Job payload must exactly match the allowlisted execution specification.

## QA

The worker verifies ZIP safety, expected files, manifest schema, file sizes and SHA-256 hashes, and glTF binary headers/version. It caps the archive at 20 MiB and rejects path traversal and duplicate entries. CI separately imports and launches the Godot project headlessly.

This is structural QA, not visual review or proof of engine compatibility on every device. No sales, marketplace acceptance or customer satisfaction is inferred.

## Delivery and non-actions

On successful QA the fulfillment job reaches `delivery_ready`. The artifact is stored under the configured local artifact root. The worker does not submit, upload, publish, contact customers, claim external work, sign wallet transactions, transfer funds or recognize revenue.

## Remaining production work

- Connect the verifiers to the production agent identity vault and owner-signature authorization service.
- Provide durable, isolated cloud storage and a supervised runtime.
- Add further explicit capability handlers with per-agent resource/time/output limits.
- Add visual review and a human-approved delivery package workflow.

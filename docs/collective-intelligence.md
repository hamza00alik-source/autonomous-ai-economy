# Collective Intelligence and outcome-backed learning

The Collective Learning Engine closes the loop between recorded work and shared memory. It stores observations, detects repeated outcome patterns, and creates a proposed lesson for owner review. It never approves a lesson automatically.

## Learning loop

1. An agent or owner records an observed outcome with a stable pattern key, outcome label, concrete observation, recorder identity, and at least one evidence/task reference.
2. The engine groups observations by exact pattern key and outcome label.
3. After two matching observations (configurable in Python, default two), it creates one shared-brain proposal for that pattern/outcome.
4. The proposal preserves the observations and source references and is marked as a hypothesis, not a causal fact.
5. The owner reviews the proposal. Only approved lessons are visible through normal shared-brain recall.
6. The opportunity pipeline's research and analysis specialists retrieve relevant approved lessons from the same shared brain.

Different outcomes (worked, failed, mixed) are never merged into one pattern proposal. The first proposal for each exact pattern/outcome pair is emitted once; later observations remain in the outcome history but do not silently rewrite the proposal.

## CLI

Record an observed result:

```bash
economy learning-record \
  --pattern "marketplace-fee-check" \
  --outcome worked \
  --observation "The current fee schedule was included in the pricing estimate." \
  --observed-by business-operations \
  --evidence-ref "task:YOUR_TASK_ID" \
  --evidence-ref "https://official-marketplace.example/fees"
```

Record a failure the same way with `--outcome failed`. Use `mixed` when the observed result is genuinely mixed; do not force a success/failure label.

Inspect progress:

```bash
economy learning-summary
economy brain-list --status proposed
```

After checking the underlying records, the owner can approve or reject the proposed lesson:

```bash
economy brain-review MEMORY_ID --decision approved --note "Reviewed both outcome records and their sources."
```

## Storage

- `./data/learning.sqlite3`: append-only outcome observations and proposal-emission index.
- `./data/brain.sqlite3`: shared lessons and owner review history.

Back up both files together. This local prototype does not provide encryption, multi-host replication, immutable cryptographic audit, or automated backup.

## What self-improvement means here

This version supports evidence-linked organizational learning: the team can remember outcomes, notice repeated patterns, and make reviewable improvements available to all connected agents. It does not fine-tune a model, prove causality, automatically change code/prompts/policies, or independently verify the evidence. The current deterministic agents do not learn new reasoning capabilities from a lesson; the pipeline supplies approved lessons as context for its research and analysis stages. Model-backed reasoning, semantic retrieval, evaluations, and safe deployment of tested workflow changes are future work.

## Cross-repository design inputs

The implementation selectively uses patterns already present in the user's repositories:
- AI Operating System: provenance-first discovery, explicit unknowns, evidence capture, sandbox testing, and owner gates.
- Automaton: bounded context, persistent state, and audit trails. Its self-replication, wallet autonomy, and self-modification are deliberately excluded.
- ETI Research Core: reproducible evaluation and independent risk gates. Its live trading/execution code is deliberately excluded.

These are design references, not copied runtime dependencies. No other repository is merged into this project.

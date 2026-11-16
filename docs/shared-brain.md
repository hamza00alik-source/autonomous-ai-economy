# Shared Brain: team memory and controlled learning

The economy has one shared, persistent SQLite memory store. Any agent can be given a `SharedBrainContext` for its own agent ID. It can recall the same owner-approved lessons as every other agent and propose new lessons from work it has completed.

## Learning lifecycle

`proposed → approved` or `proposed → rejected`

- A proposal stores its title, lesson, category, tags, source references, confidence estimate, creator agent and timestamp.
- Proposed lessons are not returned by normal recall.
- The owner must review each proposal with a written note.
- Approved lessons become available to all agents through shared recall.
- Rejected lessons remain in the audit history but are excluded from normal recall.
- A decision is immutable in this first version; corrections should be added as a new proposal rather than silently rewriting history.

## CLI

Propose a lesson:

```bash
economy brain-propose --title "Marketplace fee lesson" --lesson "Include listing and payment fees in unit economics." --category cost_validation --agent market-research --tag fees --source-ref https://example.org/fee-policy --confidence 0.8
```

List items awaiting review:

```bash
economy brain-list --status proposed
```

Approve only after checking the source and lesson:

```bash
economy brain-review MEMORY_ID --decision approved --note "Checked against the current marketplace fee schedule."
```

Reject an unsupported or unsafe lesson:

```bash
economy brain-review MEMORY_ID --decision rejected --note "Source does not support this claim."
```

Retrieve approved shared lessons:

```bash
economy brain-recall "marketplace fees pricing"
```

The database is stored at `./data/brain.sqlite3` by default. Keep this local file private and backed up; it is not encrypted or tamper-proof.

## Agent integration

Inject a context into any specialist:

```python
from economy.shared_brain import SharedBrain, SharedBrainContext

brain = SharedBrain("./data/brain.sqlite3")
memory = SharedBrainContext(brain, agent_id="market-research")

relevant_lessons = memory.recall("research marketplace pricing")
proposal = memory.propose_learning(
    title="New research lesson",
    lesson="Record the original source URL and date for each material claim.",
    category="research_quality",
    source_refs=["https://example.org/source"],
    tags=["provenance", "research"],
    confidence=0.7,
)
```

This is a shared memory interface, not a model that independently reasons or trains itself. Agents can retrieve approved context and suggest lessons; the current deterministic agents do not become more capable automatically. A future model-backed agent may use this context, but must still treat retrieved content as untrusted input and respect the same permissions.

## Safety boundary

The brain does not modify agent source code, prompts, permissions, tool access, treasury rules, or approval policies. It does not promote its own proposals, invent evidence, browse sources, or verify claims. Confidence is a recorded estimate, not proof. The database is a local prototype store; production use requires access controls, backups, encryption, migration strategy, and stronger audit integrity.

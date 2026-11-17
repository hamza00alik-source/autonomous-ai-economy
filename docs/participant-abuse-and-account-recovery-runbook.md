# Participant Abuse Review and Account-Lock Runbook

This runbook describes the current local prototype controls. It is not a production incident-response service and does not replace legal, privacy, security, or provider procedures.

## Scope and limitations

The local SQLite registry enforces per-participant rolling quotas for key-binding challenges (5/hour), key-rotation challenges (5/hour), task-offer creation (10/hour), and task-offer responses (30/hour). Quota events are retained for at most 30 days. Rejected operations create or increment an owner-review case.

These limits are participant-scoped, not IP/network-wide. They do not stop Sybil registration, distributed abuse, credential stuffing, volumetric denial-of-service, malicious uploads, or attacks against a public edge. The local prototype does not provide a public admin console, paging/alerting, case assignment, appeal workflow, or production evidence-retention controls.

## Review a signal

1. Preserve the relevant local database and application logs before changing records if an incident is suspected. Do not copy private keys, authentication secrets, raw identity documents, or unnecessary personal data into a case note.
2. List open cases:

   ```bash
   economy abuse-review-list --status open --limit 100
   ```

3. Review the participant, operation, signal count and timestamps in context. A quota rejection is a rate-limit event, not proof of malicious intent. Shared devices, retrying clients, clock problems and legitimate bursts can produce signals.
4. Record a bounded review outcome:

   ```bash
   economy abuse-review --case-id CASE_ID --decision monitor --reviewer OWNER_HANDLE --note "Reasoned review summary"
   ```

   Decisions are `dismiss`, `monitor`, or `escalate`. These are review records only. None automatically suspends, restricts, or reinstates an account.
5. For an escalated matter, preserve the minimal evidence needed for a separate owner/security/legal decision. Do not treat the prototype review command as an enforcement mechanism.

## Suspected account or signing-key compromise

1. Stop using the suspected credential. Do not ask anyone to send a seed phrase, private key, password, or raw identity document through chat or issue trackers.
2. If the authenticated participant can still sign securely and explicitly requests a lock, use the authenticated `POST /v1/participants/me/security-lock` operation with the exact confirmation body documented in the public API security specification.
3. The lock suspends the participant and invalidates pending key-binding and rotation challenges. Subsequent signed requests should be denied. Preserve the security-event history for incident review.
4. The current prototype has **no self-service unlock or implemented account recovery**. Do not manually edit the SQLite participant status or bypass the authentication checks to restore access.
5. Recovery requires an offline owner-controlled process: verify control of the underlying account/organization through an independently established channel, establish authority to act, assess compromise scope, review key history and security events, revoke compromised credentials through a separately reviewed procedure, and document the decision. The prototype does not implement this recovery workflow, so a locked account remains suspended until a future reviewed recovery feature exists.
6. If there is suspected exposure of platform infrastructure, isolate the affected host and rotate relevant platform credentials using the infrastructure provider's incident procedures. The local participant lock does not rotate platform secrets or contain host compromise.

## Do not

- Automatically suspend participants from quota signals or weak heuristics.
- Treat an unverified handle, email claim, participant ID, or replacement key as sufficient identity proof.
- Expose the local WSGI prototype, SQLite files, or local CLI to the public internet.
- Make a public accusation or disclose a participant's private case details.
- Promise account restoration, financial recovery, or a specific incident outcome before evidence and authority are established.

## Production prerequisites

Before public launch, add trusted edge/network rate limits, Sybil and registration-abuse controls, authenticated owner administration with MFA, case assignment and audit history, secure notification/escalation, privacy-reviewed retention, appeals, independently tested account recovery, security monitoring, backup/restore drills, and a documented incident commander/on-call process. Independently test lockout, key revocation, recovery, and false-positive handling.

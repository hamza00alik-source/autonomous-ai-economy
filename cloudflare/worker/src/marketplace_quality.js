const MIN_DRAFT_CHARS = 80;

function safeText(value, limit = 20000) {
  return typeof value === "string" ? value.trim().slice(0, limit) : "";
}

const SOURCE_PATTERN = /https?:\/\/[^\s)\]}>,]+/gi;
const TODO_PATTERN = /\b(todo|tbd|placeholder|insert here|lorem ipsum|not completed|unable to complete)\b/i;
const CLAIM_PATTERN = /\b(I verified|verified live|confirmed current|checked the website|tested successfully|ran the test)\b/i;

/**
 * Deterministic quality gate for private task drafts.
 * This is a screening aid, not proof of factual accuracy or acceptance.
 */
export function qualityCheckDraft(task, draft) {
  const title = safeText(task?.title, 1000);
  const body = safeText(draft, 20000);
  const checks = [];
  const blockers = [];

  checks.push({ id: "task_context", passed: Boolean(title), note: title ? "Task title present" : "Missing task title" });
  if (!title) blockers.push("missing_task_title");

  checks.push({ id: "draft_content", passed: body.length >= MIN_DRAFT_CHARS, note: body.length >= MIN_DRAFT_CHARS ? "Draft has substantive length" : "Draft is empty or too short" });
  if (body.length < MIN_DRAFT_CHARS) blockers.push("draft_too_short");

  const hasTodo = TODO_PATTERN.test(body);
  checks.push({ id: "unfinished_markers", passed: !hasTodo, note: hasTodo ? "Unfinished/placeholder language found" : "No obvious unfinished markers" });
  if (hasTodo) blockers.push("unfinished_markers_found");

  const hasSourceLinks = SOURCE_PATTERN.test(body);
  checks.push({ id: "source_links", passed: hasSourceLinks, note: hasSourceLinks ? "At least one source URL included" : "No source URL detected; factual claims may need evidence" });

  const hasSelfCheck = /\b(self[- ]?check|quality check|qa|checklist|limitations|assumptions)\b/i.test(body);
  checks.push({ id: "self_review", passed: hasSelfCheck, note: hasSelfCheck ? "Self-review/assumptions section detected" : "No explicit self-review detected" });
  if (!hasSelfCheck) blockers.push("missing_self_review");

  const hasVerificationClaims = CLAIM_PATTERN.test(body);
  checks.push({ id: "verification_claims", passed: !hasVerificationClaims, note: hasVerificationClaims ? "Contains verification claims that require evidence review" : "No obvious unsupported verification claims detected" });
  if (hasVerificationClaims) blockers.push("verification_claims_require_evidence");

  return {
    status: blockers.length === 0 ? "submission_candidate" : "needs_revision",
    checks,
    blockers,
    sourceUrls: [...new Set(body.match(SOURCE_PATTERN) || [])],
    assessedAt: new Date().toISOString(),
    warning: "Automated QA is a screening aid only. A human must review task criteria, factual claims, evidence, and platform rules before submission."
  };
}

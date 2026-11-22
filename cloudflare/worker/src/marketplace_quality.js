const MIN_DRAFT_CHARS = 80;

function safeText(value, limit = 20000) {
  return typeof value === "string" ? value.trim().slice(0, limit) : "";
}

const SOURCE_PATTERN = /https?:\/\/[^\s)\]}>,]+/gi;
const TODO_PATTERN = /\b(todo|tbd|placeholder|insert here|lorem ipsum|not completed|unable to complete)\b/i;
const CLAIM_PATTERN = /\b(I verified|verified live|confirmed current|checked the website|tested successfully|ran the test)\b/i;

/**
 * Deterministic quality gate for private task drafts.
 * This is a screening aid, not proof of factual accuracy or buyer acceptance.
 */
export function qualityCheckDraft(task, draft, independentReview = null) {
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

  // Do not call RegExp.test on a global expression: its lastIndex is stateful.
  const sourceUrls = [...new Set([...body.matchAll(new RegExp(SOURCE_PATTERN.source, "gi"))].map(match => match[0]))];
  checks.push({ id: "source_links", passed: sourceUrls.length > 0, note: sourceUrls.length ? "At least one source URL included; URL validity is not established" : "No source URL detected; factual claims may need evidence" });

  const hasSelfCheck = /\b(self[- ]?check|quality check|qa|checklist|limitations|assumptions)\b/i.test(body);
  checks.push({ id: "self_review", passed: hasSelfCheck, note: hasSelfCheck ? "Self-review/assumptions section detected" : "No explicit self-review detected" });
  if (!hasSelfCheck) blockers.push("missing_self_review");

  const hasVerificationClaims = CLAIM_PATTERN.test(body);
  checks.push({ id: "verification_claims", passed: !hasVerificationClaims, note: hasVerificationClaims ? "Contains verification claims requiring evidence review" : "No obvious unsupported verification claims detected" });
  if (hasVerificationClaims) blockers.push("verification_claims_require_evidence");

  const reviewPassed = independentReview?.pass === true &&
    Array.isArray(independentReview?.issues) && independentReview.issues.length === 0 &&
    Array.isArray(independentReview?.failedCriteria) && independentReview.failedCriteria.length === 0;
  checks.push({ id: "independent_review", passed: reviewPassed, note: reviewPassed ? "Independent reviewer passed the exact draft" : "Missing, failed, or incomplete independent review" });
  if (!reviewPassed) blockers.push("independent_review_not_passed");

  const requiredCriteria = Array.isArray(task?.acceptanceCriteria) ? task.acceptanceCriteria : [];
  const reviewedCriteria = Array.isArray(independentReview?.criteria) ? independentReview.criteria : [];
  const criteriaCovered = requiredCriteria.every(required =>
    reviewedCriteria.some(item => item?.criterion === required && item?.passed === true && item?.evidence?.trim())
  ) && reviewedCriteria.length === requiredCriteria.length;
  checks.push({ id: "acceptance_criteria", passed: criteriaCovered, note: criteriaCovered ? "Every supplied acceptance criterion has a passing evidence note" : "Acceptance criteria are missing, failed, or not individually evidenced" });
  if (!criteriaCovered) blockers.push("acceptance_criteria_not_verified");

  return {
    status: blockers.length === 0 ? "submission_candidate" : "needs_revision",
    checks,
    blockers,
    sourceUrls,
    acceptanceCriteriaCount: requiredCriteria.length,
    independentlyReviewed: reviewPassed,
    assessedAt: new Date().toISOString(),
    warning: "Automated QA is a screening aid only. It cannot prove external facts, platform compliance, or buyer acceptance. Submission remains a separately authorized action."
  };
}

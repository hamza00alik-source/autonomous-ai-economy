const MIN_DRAFT_CHARS = 80;

function safeText(value, limit = 20000) {
  return typeof value === "string" ? value.trim().slice(0, limit) : "";
}

const SOURCE_PATTERN = /https?:\/\/[^\s)\]}>,\"']+/gi;
const TODO_PATTERN = /\b(todo|tbd|placeholder|insert here|lorem ipsum|not completed|unable to complete)\b/i;
const CLAIM_PATTERN = /\b(I verified|verified live|confirmed current|checked the website|tested successfully|ran the test)\b/i;
const RESEARCH_PATTERN = /\b(research|investigate|fact[- ]check|market analysis|compare|comparison|cite|citations|sources)\b/i;

function extractUrls(body) {
  const candidates = [...new Set([...body.matchAll(new RegExp(SOURCE_PATTERN.source, "gi"))].map(match => match[0].replace(/[.,;:!?]+$/, "")))];
  const valid = [];
  const invalid = [];
  for (const candidate of candidates) {
    try {
      const parsed = new URL(candidate);
      if ((parsed.protocol !== "https:" && parsed.protocol !== "http:") || !parsed.hostname.includes(".")) {
        invalid.push(candidate);
      } else {
        valid.push(parsed.href);
      }
    } catch {
      invalid.push(candidate);
    }
  }
  return { valid: [...new Set(valid)], invalid: [...new Set(invalid)] };
}

/**
 * Deterministic quality gate for private task drafts.
 * URL syntax is checked locally; remote source content is not fetched or verified.
 */
export function qualityCheckDraft(task, draft, independentReview = null) {
  const title = safeText(task?.title, 1000);
  const description = safeText(task?.description, 12000);
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

  const { valid: sourceUrls, invalid: invalidSourceUrls } = extractUrls(body);
  const needsSources = RESEARCH_PATTERN.test(title + "\n" + description);
  const sourcesPass = !needsSources || sourceUrls.length > 0;
  // No trusted source-fetching adapter is wired into this worker yet.
  // Do not let a syntactically valid URL masquerade as verified research evidence.
  const sourceContentVerified = false;
  checks.push({
    id: "source_links",
    passed: sourcesPass && invalidSourceUrls.length === 0,
    note: invalidSourceUrls.length
      ? "One or more source URLs are syntactically invalid"
      : needsSources && !sourceUrls.length
        ? "This research/comparison task requires at least one syntactically valid source URL"
        : sourceUrls.length
          ? "Source URL syntax is valid; remote content and factual support are not verified"
          : "No source URL required by task wording",
  });
  if (!sourcesPass) blockers.push("research_sources_missing");
  if (invalidSourceUrls.length) blockers.push("invalid_source_urls");
  if (needsSources && !sourceContentVerified) blockers.push("source_content_not_verified");

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
    reviewedCriteria.some(item => item?.criterion === required && item?.passed === true &&
      typeof item?.evidence === "string" && item.evidence.trim() && body.includes(item.evidence))
  ) && reviewedCriteria.length === requiredCriteria.length;
  checks.push({ id: "acceptance_criteria", passed: criteriaCovered, note: criteriaCovered ? "Every supplied acceptance criterion has an exact evidence excerpt" : "Acceptance criteria are missing, failed, or lack exact evidence excerpts" });
  if (!criteriaCovered) blockers.push("acceptance_criteria_not_verified");

  return {
    status: blockers.length === 0 ? "submission_candidate" : "needs_revision",
    checks,
    blockers,
    sourceUrls,
    invalidSourceUrls,
    sourceContentVerified,
    acceptanceCriteriaCount: requiredCriteria.length,
    independentlyReviewed: reviewPassed,
    assessedAt: new Date().toISOString(),
    warning: "Automated QA is a screening aid only. URL syntax is not source verification. It cannot prove external facts, platform compliance, or buyer acceptance. Submission remains a separately authorized action."
  };
}

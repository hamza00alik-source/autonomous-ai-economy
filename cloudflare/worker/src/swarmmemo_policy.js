const MAX_SCREEN_TEXT = 24_000;

const PUBLIC_RESEARCH_MARKERS = [
  /\bpublic(?:ly available)?\b/i,
  /\bopen[- ]data\b/i,
  /\bpublic (?:dataset|endpoint|records?|sources?|information|filings?)\b/i,
  /\bgovernment (?:data|statistics|records?)\b/i,
  /\b(?:official )?statistics\b/i,
];

const DELIVERABLE_MARKERS = [
  /\b(?:brief|report|summary|summar(?:y|ize)|research|verify|compare|analysis|findings)\b/i,
];

const HARD_BLOCK_MARKERS = [
  /\b(?:password|passphrase|private key|recovery phrase|seed phrase|api key|secret token|credentials?)\b/i,
  /\b(?:personal data|sensitive data|private records|nonpublic|non-public|doxx|social security|passport number)\b/i,
  /\b(?:bank transfer|wire transfer|send funds|withdraw|deposit|purchase|buy credits|pay(?:ment)?|invoice|wallet address|crypto(?:currency)?|\busdc\b|\beth\b)\b/i,
  /\b(?:log ?in|sign ?in|create an account|register an account|account verification|identity verification)\b/i,
  /\b(?:install software|run code|execute code|deploy|production access|admin access|database access)\b/i,
  /\b(?:send an email|contact the requester|direct message|dm the|publish|post publicly|social media post)\b/i,
];

export function screenSwarmMemoTask(task) {
  if (!task || typeof task !== "object") return { allowed: false, reason: "invalid_task" };
  if (task.board_state !== "open") return { allowed: false, reason: "task_not_open" };
  if (task.eligible !== 1 && task.eligible !== true) return { allowed: false, reason: "platform_not_claimable" };
  if (task.simulated === 1 || task.simulated === true) return { allowed: false, reason: "simulated_task" };
  if (task.request_truncated === 1 || task.request_truncated === true) return { allowed: false, reason: "full_task_text_required" };

  const title = typeof task.title === "string" ? task.title : "";
  const body = typeof task.task_text === "string" ? task.task_text : "";
  const text = (title + "\n" + body).trim();
  if (text.length < 40 || text.length > MAX_SCREEN_TEXT) return { allowed: false, reason: "task_text_out_of_bounds" };

  const blocked = HARD_BLOCK_MARKERS.find((pattern) => pattern.test(text));
  if (blocked) return { allowed: false, reason: "requires_restricted_or_external_action" };
  if (!PUBLIC_RESEARCH_MARKERS.some((pattern) => pattern.test(text))) {
    return { allowed: false, reason: "not_clearly_public_information" };
  }
  if (!DELIVERABLE_MARKERS.some((pattern) => pattern.test(text))) {
    return { allowed: false, reason: "no_bounded_research_deliverable" };
  }

  return {
    allowed: true,
    reason: "public_research_preparation_only",
    external_action_required: /\b(?:claim|submit|upload|send|publish|post)\b/i.test(text),
  };
}

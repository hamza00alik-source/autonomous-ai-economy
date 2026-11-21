const FEED_URL = "https://swarmmemo.com/api/works?kind=rewarded&limit=10";
const MAX_FEED_BYTES = 1_000_000;
const MAX_TASK_TEXT = 24_000;

function safeString(value, max = 500) {
  return typeof value === "string" ? value.trim().slice(0, max) : "";
}

export function feedCursor(payload) {
  return safeString(payload?.since || payload?.data?.since, 500);
}

export function feedUnchanged(payload) {
  return payload?.unchanged === true || payload?.data?.unchanged === true;
}

function nextPageCursor(payload) {
  return safeString(payload?.next_cursor || payload?.data?.next_cursor, 500);
}

function normalizeDeadline(value) {
  if (typeof value === "number" && Number.isFinite(value) && value > 0) {
    return new Date(value * 1000).toISOString();
  }
  return safeString(value, 80) || null;
}

function workRows(payload) {
  return Array.isArray(payload?.works) ? payload.works
    : Array.isArray(payload?.items) ? payload.items
    : Array.isArray(payload?.data?.works) ? payload.data.works
    : null;
}

export function usdcNextRows(payload) {
  const rows = Array.isArray(payload?.usdc_next) ? payload.usdc_next
    : Array.isArray(payload?.data?.usdc_next) ? payload.data.usdc_next : [];
  return rows.flatMap((row) => {
    if (!row || typeof row !== "object" || Array.isArray(row)) return [];
    const taskId = safeString(row.id || row.work_id, 128);
    if (!taskId) return [];
    return [{
      task_id: taskId,
      title: safeString(row.title, 300),
      usdc_per_result: safeString(row.usdc_per_result, 40),
      next_open_at: normalizeDeadline(row.next_open_at),
    }];
  });
}

export function normalizeSwarmMemoFeed(payload) {
  const rows = workRows(payload);
  if (!rows) throw new Error("SwarmMemo feed schema did not contain a works array");
  return rows.flatMap((row) => {
    if (!row || typeof row !== "object" || Array.isArray(row)) return [];
    const taskId = safeString(row.id || row.message_id || row.work_id, 128);
    const request = row.request && typeof row.request === "object" ? row.request : {};
    const title = safeString(row.title || request.title, 300);
    const rawTaskText = request.text || row.text || row.description;
    const taskText = safeString(rawTaskText, MAX_TASK_TEXT);
    if (!taskId || !title || !taskText) return [];
    const requestTruncated = request.truncated === true ||
      (typeof rawTaskText === "string" && rawTaskText.length > MAX_TASK_TEXT);
    const reward = row.reward && typeof row.reward === "object" ? row.reward : {};
    const standing = row.standing && typeof row.standing === "object" ? row.standing : null;
    const usdcNext = row.usdc_next && typeof row.usdc_next === "object" ? row.usdc_next : null;
    // Keep existing reward fields intact while preserving conditional USDC tiers, room and opening schedule.
    const rewardSnapshot = {
      ...reward,
      ...(standing ? { standing } : {}),
      ...(usdcNext ? { usdc_next: usdcNext } : {}),
    };
    const requesterRecord = row.requester_record && typeof row.requester_record === "object"
      ? row.requester_record : null;
    return [{
      task_id: taskId,
      title,
      room: safeString(row.room || request.room, 80),
      requester: safeString(row.requester?.handle || row.requester || row.requester_handle || row.requester_author || row.author, 120),
      task_text: taskText,
      request_truncated: requestTruncated ? 1 : 0,
      simulated: row.simulated === true ? 1 : 0,
      reward_json: JSON.stringify(rewardSnapshot),
      requester_record_json: requesterRecord ? JSON.stringify(requesterRecord).slice(0, 16_000) : null,
      deadline: normalizeDeadline(row.deadline || row.deadline_at),
      board_state: safeString(row.state || "open", 40).toLowerCase(),
      eligible: row.simulated !== true && !requestTruncated && row.state === "open"
        && (typeof row.claimable === "boolean" ? row.claimable
          : row.eligibility === "open" || row.eligible === true) ? 1 : 0,
      eligibility_reason: safeString(row.eligible_reason || row.eligibility, 500) || null,
    }];
  });
}

async function readJsonLimited(response) {
  if (!response.ok) throw new Error("SwarmMemo returned HTTP " + response.status);
  const declaredLength = Number(response.headers.get("content-length") || 0);
  if (declaredLength > MAX_FEED_BYTES) throw new Error("SwarmMemo response exceeded size limit");
  const raw = await response.text();
  if (new TextEncoder().encode(raw).length > MAX_FEED_BYTES) throw new Error("SwarmMemo response exceeded size limit");
  return JSON.parse(raw);
}

async function fetchFullWork(taskId, fetchImpl) {
  const response = await fetchImpl("https://swarmmemo.com/api/work/" + encodeURIComponent(taskId), {
    method: "GET",
    headers: { accept: "application/json", "user-agent": "AutonomousAIEconomy/0.1" },
    signal: AbortSignal.timeout(12_000),
  });
  const payload = await readJsonLimited(response);
  const work = payload?.data?.work || payload?.work;
  if (!work || typeof work !== "object") throw new Error("SwarmMemo full-work response schema changed");
  return work;
}

export async function pollSwarmMemo(env, fetchImpl = fetch) {
  const now = new Date().toISOString();
  try {
    const previous = await env.DB.prepare(
      "SELECT since_cursor,page_cursor FROM swarmmemo_poll_state WHERE source='rewarded'"
    ).first();
    const url = new URL(FEED_URL);
    if (previous?.since_cursor) url.searchParams.set("since", previous.since_cursor);
    if (previous?.page_cursor) url.searchParams.set("cursor", previous.page_cursor);
    let response = await fetchImpl(url.toString(), {
      method: "GET",
      headers: { accept: "application/json", "user-agent": "AutonomousAIEconomy/0.1" },
      signal: AbortSignal.timeout(12_000),
    });
    // SwarmMemo may invalidate old incremental cursors after feed changes.
    // A single HTTP 400 retry without cursors recovers discovery without writes.
    if (response.status === 400 && (previous?.since_cursor || previous?.page_cursor)) {
      const freshUrl = new URL(FEED_URL);
      response = await fetchImpl(freshUrl.toString(), {
        method: "GET",
        headers: { accept: "application/json", "user-agent": "AutonomousAIEconomy/0.1" },
        signal: AbortSignal.timeout(12_000),
      });
    }
    const payload = await readJsonLimited(response);
    const pollCursor = feedCursor(payload) || previous?.since_cursor || null;
    const unchanged = feedUnchanged(payload);
    const rows = unchanged ? [] : workRows(payload);
    if (!unchanged && !rows) throw new Error("SwarmMemo feed schema did not contain a works array");
    const normalized = normalizeSwarmMemoFeed({ works: rows || [] });
    const previewById = new Map(normalized.map((preview) => [preview.task_id, preview]));
    for (const scheduled of usdcNextRows(payload)) {
      const existing = previewById.get(scheduled.task_id);
      if (existing) existing.usdc_next = scheduled;
      else previewById.set(scheduled.task_id, {
        task_id: scheduled.task_id,
        title: scheduled.title || "Scheduled USDC task",
        task_text: "",
        request_truncated: 1,
        simulated: 0,
        eligible: 0,
        board_state: "scheduled",
        eligibility_reason: "waiting_for_usdc_window",
        usdc_next: scheduled,
      });
    }
    const hasMore = payload?.data?.has_more === true || payload?.has_more === true;
    const pageCursor = hasMore ? nextPageCursor(payload) : null;
    const tasks = (await Promise.all([...previewById.values()].map(async (preview) => {
      try {
        const fetchedWork = await fetchFullWork(preview.task_id, fetchImpl);
        const isScheduledUsdc = !!preview.usdc_next;
        const fetchedClaimable = typeof fetchedWork.claimable === "boolean"
          ? fetchedWork.claimable : (!isScheduledUsdc && preview.eligible === 1);
        const fullWork = {
          ...fetchedWork,
          id: fetchedWork.id || preview.task_id,
          simulated: typeof fetchedWork.simulated === "boolean" ? fetchedWork.simulated : preview.simulated === 1,
          state: isScheduledUsdc && !fetchedClaimable ? "scheduled" : fetchedWork.state || preview.board_state,
          eligibility: fetchedWork.eligibility || preview.eligibility_reason,
          claimable: fetchedClaimable,
          ...(preview.usdc_next ? { usdc_next: preview.usdc_next } : {}),
          request: fetchedWork.request && typeof fetchedWork.request === "object"
            ? { ...fetchedWork.request, truncated: fetchedWork.request.truncated === true }
            : { text: preview.task_text, truncated: preview.request_truncated === 1 },
        };
        const fullRows = normalizeSwarmMemoFeed({ works: [fullWork] });
        if (fullRows.length && fullRows[0].request_truncated === 0) return fullRows[0];
      } catch {
        // A scheduled USDC item without its full brief is skipped; never queue a title-only task.
      }
      if (preview.usdc_next) return null;
      return { ...preview, request_truncated: 1, eligible: 0,
        eligibility_reason: "full_task_fetch_failed" };
    }))).filter(Boolean);

    const statements = tasks.map((task) => env.DB.prepare(
      `INSERT INTO swarmmemo_work_items
       (task_id,title,room,requester,task_text,request_truncated,simulated,reward_json,requester_record_json,deadline,
        board_state,eligible,eligibility_reason,first_seen_at,last_seen_at,updated_at)
       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
       ON CONFLICT(task_id) DO UPDATE SET
        title=excluded.title,room=excluded.room,requester=excluded.requester,
        task_text=excluded.task_text,request_truncated=excluded.request_truncated,simulated=excluded.simulated,
        reward_json=excluded.reward_json,requester_record_json=excluded.requester_record_json,
        deadline=excluded.deadline,board_state=excluded.board_state,eligible=excluded.eligible,
        eligibility_reason=excluded.eligibility_reason,last_seen_at=excluded.last_seen_at,
        updated_at=excluded.updated_at`
    ).bind(task.task_id, task.title, task.room, task.requester, task.task_text,
      task.request_truncated, task.simulated, task.reward_json, task.requester_record_json, task.deadline,
      task.board_state, task.eligible, task.eligibility_reason, now, now, now));
    if (statements.length) await env.DB.batch(statements);
    await env.DB.prepare(
      `INSERT INTO swarmmemo_poll_state (source,last_success_at,last_error,last_count,last_http_status,since_cursor,page_cursor,updated_at)
       VALUES ('rewarded',?,NULL,?,?,?,?,?)
       ON CONFLICT(source) DO UPDATE SET last_success_at=excluded.last_success_at,
        last_error=NULL,last_count=excluded.last_count,last_http_status=excluded.last_http_status,
        since_cursor=excluded.since_cursor,page_cursor=excluded.page_cursor,updated_at=excluded.updated_at`
    ).bind(now, tasks.length, response.status, pollCursor, pageCursor, now).run();
    return { ok: true, unchanged, discovered: tasks.length, checked_at: now };
  } catch (error) {
    const message = safeString(error?.message || "SwarmMemo poll failed", 500);
    await env.DB.prepare(
      `INSERT INTO swarmmemo_poll_state (source,last_success_at,last_error,last_count,last_http_status,updated_at)
       VALUES ('rewarded',NULL,?,0,NULL,?)
       ON CONFLICT(source) DO UPDATE SET last_error=excluded.last_error,updated_at=excluded.updated_at`
    ).bind(message, now).run();
    return { ok: false, error: message, checked_at: now };
  }
}

export async function listSwarmMemoWork(env, limit = 50) {
  const bounded = Math.min(100, Math.max(1, Number(limit) || 50));
  const [rows, poll] = await Promise.all([
    env.DB.prepare(
      `SELECT task_id,title,room,requester,task_text,request_truncated,simulated,reward_json,requester_record_json,
        deadline,board_state,eligible,eligibility_reason,owner_approved,execution_state,
        result_message_id,last_error,first_seen_at,last_seen_at,updated_at
       FROM swarmmemo_work_items ORDER BY
        CASE WHEN board_state='open' THEN 0 ELSE 1 END,
        last_seen_at DESC LIMIT ?`
    ).bind(bounded).all(),
    env.DB.prepare("SELECT * FROM swarmmemo_poll_state WHERE source='rewarded'").first(),
  ]);
  return {
    items: (rows.results || []).map((row) => ({
      ...row,
      reward: parseJson(row.reward_json),
      requester_record: parseJson(row.requester_record_json),
      reward_json: undefined,
      requester_record_json: undefined,
    })),
    poll: poll || null,
    execution_notice: "Discovery only: no task is claimed, posted, submitted or paid by this lane. Full task text is required before approval; a configured signing identity is required before external commitments.",
  };
}

function parseJson(value) {
  if (!value) return null;
  try { return JSON.parse(value); } catch { return null; }
}

export async function approveSwarmMemoTask(env, taskId) {
  const now = new Date().toISOString();
  const result = await env.DB.prepare(
    `UPDATE swarmmemo_work_items SET owner_approved=1,
      execution_state='approved_awaiting_executor',updated_at=?
     WHERE task_id=? AND board_state='open' AND eligible=1 AND simulated=0 AND request_truncated=0
       AND execution_state='awaiting_owner_approval'`
  ).bind(now, taskId).run();
  return { approved: result.meta?.changes === 1 };
}

const FEED_URL = "https://swarmmemo.com/api/works?kind=rewarded&limit=50";
const MAX_FEED_BYTES = 1_000_000;
const MAX_TASK_TEXT = 24_000;

function safeString(value, max = 500) {
  return typeof value === "string" ? value.trim().slice(0, max) : "";
}

export function normalizeSwarmMemoFeed(payload) {
  const rows = Array.isArray(payload?.works) ? payload.works
    : Array.isArray(payload?.items) ? payload.items
    : Array.isArray(payload?.data?.works) ? payload.data.works
    : null;
  if (!rows) throw new Error("SwarmMemo feed schema did not contain a works array");
  return rows.flatMap((row) => {
    if (!row || typeof row !== "object" || Array.isArray(row)) return [];
    const taskId = safeString(row.id || row.message_id || row.work_id, 128);
    const request = row.request && typeof row.request === "object" ? row.request : {};
    const title = safeString(row.title || request.title, 300);
    const taskText = safeString(request.text || row.text || row.description, MAX_TASK_TEXT);
    if (!taskId || !title || !taskText) return [];
    const reward = row.reward && typeof row.reward === "object" ? row.reward : {};
    const requesterRecord = row.requester_record && typeof row.requester_record === "object"
      ? row.requester_record : null;
    return [{
      task_id: taskId,
      title,
      room: safeString(row.room || request.room, 80),
      requester: safeString(row.requester || row.requester_handle || row.author, 120),
      task_text: taskText,
      reward_json: JSON.stringify(reward),
      requester_record_json: requesterRecord ? JSON.stringify(requesterRecord) : null,
      deadline: safeString(row.deadline || row.deadline_at, 80) || null,
      board_state: safeString(row.state || "open", 40).toLowerCase(),
      eligible: row.eligible === true ? 1 : 0,
      eligibility_reason: safeString(row.eligible_reason, 500) || null,
      raw_json: JSON.stringify(row).slice(0, 32_000),
    }];
  });
}

export async function pollSwarmMemo(env, fetchImpl = fetch) {
  const now = new Date().toISOString();
  let response;
  try {
    response = await fetchImpl(FEED_URL, {
      method: "GET",
      headers: { accept: "application/json", "user-agent": "AutonomousAIEconomy/0.1" },
      signal: AbortSignal.timeout(12_000),
    });
    if (!response.ok) throw new Error("SwarmMemo feed returned HTTP " + response.status);
    const declaredLength = Number(response.headers.get("content-length") || 0);
    if (declaredLength > MAX_FEED_BYTES) throw new Error("SwarmMemo feed exceeded size limit");
    const raw = await response.text();
    if (new TextEncoder().encode(raw).length > MAX_FEED_BYTES) throw new Error("SwarmMemo feed exceeded size limit");
    const payload = JSON.parse(raw);
    const tasks = normalizeSwarmMemoFeed(payload);
    const statements = tasks.map((task) => env.DB.prepare(
      `INSERT INTO swarmmemo_work_items
       (task_id,title,room,requester,task_text,reward_json,requester_record_json,deadline,
        board_state,eligible,eligibility_reason,first_seen_at,last_seen_at,updated_at)
       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
       ON CONFLICT(task_id) DO UPDATE SET
        title=excluded.title,room=excluded.room,requester=excluded.requester,
        task_text=excluded.task_text,reward_json=excluded.reward_json,
        requester_record_json=excluded.requester_record_json,deadline=excluded.deadline,
        board_state=excluded.board_state,eligible=excluded.eligible,
        eligibility_reason=excluded.eligibility_reason,last_seen_at=excluded.last_seen_at,
        updated_at=excluded.updated_at`
    ).bind(task.task_id, task.title, task.room, task.requester, task.task_text,
      task.reward_json, task.requester_record_json, task.deadline, task.board_state,
      task.eligible, task.eligibility_reason, now, now, now));
    if (statements.length) await env.DB.batch(statements);
    await env.DB.prepare(
      `INSERT INTO swarmmemo_poll_state (source,last_success_at,last_error,last_count,last_http_status,updated_at)
       VALUES ('rewarded',?,NULL,?,?,?)
       ON CONFLICT(source) DO UPDATE SET last_success_at=excluded.last_success_at,
        last_error=NULL,last_count=excluded.last_count,last_http_status=excluded.last_http_status,
        updated_at=excluded.updated_at`
    ).bind(now, tasks.length, response.status, now).run();
    return { ok: true, discovered: tasks.length, checked_at: now };
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
      `SELECT task_id,title,room,requester,task_text,reward_json,requester_record_json,
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
    execution_notice: "Discovery only: no task is claimed, posted, submitted or paid by this lane. Owner approval and a configured signing identity are required before external commitments.",
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
     WHERE task_id=? AND board_state='open' AND eligible=1
       AND execution_state='awaiting_owner_approval'`
  ).bind(now, taskId).run();
  return { approved: result.meta?.changes === 1 };
}

import { loadActiveCloudFinancialPolicy, verifyOwnerSignedFinancialPolicy, financialPublicKeyFingerprint } from "./financial_policy_auth.js";

const ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{2,79}$/;
const iso = value => typeof value === "string" && Number.isFinite(Date.parse(value));
const json = value => JSON.stringify(value);

function validId(value) { return typeof value === "string" && ID.test(value); }


function canonicalObject(value) {
  if (Array.isArray(value)) return value.map(canonicalObject);
  if (value && typeof value === "object") {
    return Object.keys(value).sort().reduce((result,key)=>{result[key]=canonicalObject(value[key]);return result;},{});
  }
  return value;
}
function canonicalText(value) { return JSON.stringify(canonicalObject(value)); }
function bytesToBase64Url(bytes) {
  let binary="";
  for (const byte of bytes) binary+=String.fromCharCode(byte);
  return btoa(binary).split("=").join("").split("+").join("-").split("/").join("_");
}
function decodeBase64Url(value) {
  if(typeof value!=="string"||!/^[A-Za-z0-9_-]+$/.test(value)) return null;
  try {
    const padded=value.replace(/-/g,"+").replace(/_/g,"/")+"=".repeat((4-value.length%4)%4);
    return Uint8Array.from(atob(padded),char=>char.charCodeAt(0));
  } catch { return null; }
}
async function sha256Hex(value) {
  const digest=await crypto.subtle.digest("SHA-256",new TextEncoder().encode(value));
  return [...new Uint8Array(digest)].map(byte=>byte.toString(16).padStart(2,"0")).join("");
}

export async function createCloudOwnerEnrollmentChallenge(db,{ownerId,operatorId,now=new Date().toISOString()}={}) {
  if(!validId(ownerId)||!validId(operatorId)||ownerId===operatorId) return {ok:false,reason:"invalid_owner_or_operator_id"};
  const existing=await db.prepare("SELECT owner_id,operator_id,key_fingerprint FROM financial_owner_enrollments WHERE owner_id=? OR operator_id=?")
    .bind(ownerId,operatorId).first();
  if(existing) return {ok:false,reason:"owner_or_operator_already_enrolled"};
  await db.prepare("UPDATE financial_owner_enrollment_challenges SET consumed_at=? WHERE owner_id=? AND consumed_at IS NULL AND expires_at<=?")
    .bind(now,ownerId,now).run();
  const pending=await db.prepare("SELECT challenge_id,challenge,expires_at FROM financial_owner_enrollment_challenges WHERE owner_id=? AND operator_id=? AND consumed_at IS NULL AND expires_at>?")
    .bind(ownerId,operatorId,now).first();
  if(pending) return {ok:true,...pending,owner_id:ownerId,operator_id:operatorId,reused:true};
  const challengeId=crypto.randomUUID();
  const random=crypto.getRandomValues(new Uint8Array(32));
  const challenge="aae-owner-enrollment:v1:"+ownerId+":"+operatorId+":"+challengeId+":"+bytesToBase64Url(random);
  const expiresAt=new Date(Date.parse(now)+5*60*1000).toISOString();
  try {
    await db.prepare("INSERT INTO financial_owner_enrollment_challenges(challenge_id,owner_id,operator_id,challenge,expires_at,created_at) VALUES(?,?,?,?,?,?)")
      .bind(challengeId,ownerId,operatorId,challenge,expiresAt,now).run();
  } catch {
    const raced=await db.prepare("SELECT challenge_id,challenge,expires_at FROM financial_owner_enrollment_challenges WHERE owner_id=? AND operator_id=? AND consumed_at IS NULL AND expires_at>?")
      .bind(ownerId,operatorId,now).first();
    if(!raced) return {ok:false,reason:"enrollment_challenge_unavailable"};
    return {ok:true,...raced,owner_id:ownerId,operator_id:operatorId,reused:true};
  }
  return {ok:true,challenge_id:challengeId,challenge,expires_at:expiresAt,owner_id:ownerId,operator_id:operatorId,reused:false};
}

export async function completeCloudOwnerEnrollment(db,{
  ownerId,operatorId,challengeId,publicKeyJwk,signatureBase64Url,agentIds,currencies=["USD"],now=new Date().toISOString()
}={}) {
  if(!validId(ownerId)||!validId(operatorId)||!validId(challengeId)||ownerId===operatorId)
    return {ok:false,reason:"invalid_enrollment_identity"};
  if(!Array.isArray(agentIds)||agentIds.length<1||agentIds.length>25||
     agentIds.some(id=>!validId(id))||new Set(agentIds).size!==agentIds.length)
    return {ok:false,reason:"invalid_agent_ids"};
  if(!Array.isArray(currencies)||currencies.length<1||currencies.length>5||
     currencies.some(code=>typeof code!=="string"||!/^[A-Z]{3}$/.test(code))||new Set(currencies).size!==currencies.length)
    return {ok:false,reason:"invalid_currency_codes"};
  if(!publicKeyJwk||typeof publicKeyJwk!=="object"||Array.isArray(publicKeyJwk)||
     Object.keys(publicKeyJwk).some(key=>!["kty","crv","x"].includes(key))||
     publicKeyJwk.kty!=="OKP"||publicKeyJwk.crv!=="Ed25519"||typeof publicKeyJwk.x!=="string"||"d" in publicKeyJwk)
    return {ok:false,reason:"invalid_public_key_jwk"};
  const fingerprint=await financialPublicKeyFingerprint(publicKeyJwk);
  if(!fingerprint) return {ok:false,reason:"invalid_public_key"};
  const challengeRow=await db.prepare(
    "SELECT challenge_id,owner_id,operator_id,challenge,expires_at,consumed_at FROM financial_owner_enrollment_challenges WHERE challenge_id=?"
  ).bind(challengeId).first();
  if(!challengeRow||challengeRow.owner_id!==ownerId||challengeRow.operator_id!==operatorId)
    return {ok:false,reason:"enrollment_challenge_not_found"};
  const challengeConsumed=Boolean(challengeRow.consumed_at);
  const challengeExpired=Date.parse(challengeRow.expires_at)<=Date.parse(now);
  if(challengeExpired&&!challengeConsumed) return {ok:false,reason:"enrollment_challenge_expired_or_consumed"};
  const signedPayload={
    version:1,owner_id:ownerId,operator_id:operatorId,challenge_id:challengeId,
    challenge:challengeRow.challenge,public_key_fingerprint:fingerprint,
    agent_ids:[...agentIds].sort(),currencies:[...currencies].sort()
  };
  const canonicalPayload=canonicalText(signedPayload);
  const signature=decodeBase64Url(signatureBase64Url);
  if(!signature||signature.length!==64) return {ok:false,reason:"invalid_enrollment_signature_encoding"};
  try {
    const key=await crypto.subtle.importKey("jwk",{
      crv:"Ed25519",ext:true,key_ops:["verify"],kty:"OKP",x:publicKeyJwk.x
    },{name:"Ed25519"},false,["verify"]);
    if(!await crypto.subtle.verify({name:"Ed25519"},key,signature,new TextEncoder().encode(canonicalPayload)))
      return {ok:false,reason:"invalid_enrollment_proof"};
  } catch { return {ok:false,reason:"enrollment_signature_verification_failed"}; }
  const payloadHash=await sha256Hex(canonicalPayload);
  const prior=await db.prepare("SELECT owner_id,operator_id,challenge_id,key_fingerprint,payload_hash FROM financial_owner_enrollments WHERE owner_id=? OR operator_id=?")
    .bind(ownerId,operatorId).first();
  if(prior) return prior.challenge_id===challengeId&&prior.key_fingerprint===fingerprint&&prior.payload_hash===payloadHash
    ? {ok:true,idempotent:true,owner_id:ownerId,operator_id:operatorId,agent_ids:agentIds}
    : {ok:false,reason:"owner_or_operator_already_enrolled"};
  if(challengeConsumed) return {ok:false,reason:"enrollment_challenge_expired_or_consumed"};
  const occupied=await db.prepare("SELECT participant_id,participant_type FROM financial_participants WHERE participant_id IN ("+
    [ownerId,operatorId,...agentIds].map(()=>"?").join(",")+")")
    .bind(ownerId,operatorId,...agentIds).all();
  if((occupied.results||[]).length) return {ok:false,reason:"participant_id_already_in_use"};
  const ownerNow=now;
  const ownerInsert=db.prepare(
    "INSERT INTO financial_participants(participant_id,participant_type,status,created_at,updated_at) " +
    "SELECT ?,'owner','active',?,? WHERE EXISTS(SELECT 1 FROM financial_owner_enrollments WHERE owner_id=? AND payload_hash=?)"
  ).bind(ownerId,ownerNow,ownerNow,ownerId,payloadHash);
  const operatorInsert=db.prepare(
    "INSERT INTO financial_participants(participant_id,participant_type,status,owner_id,public_key_jwk,key_fingerprint,created_at,updated_at) " +
    "SELECT ?,'operator','active',?,?,?,?,? WHERE EXISTS(SELECT 1 FROM financial_owner_enrollments WHERE owner_id=? AND payload_hash=?)"
  ).bind(operatorId,ownerId,JSON.stringify({kty:"OKP",crv:"Ed25519",x:publicKeyJwk.x}),fingerprint,ownerNow,ownerNow,ownerId,payloadHash);
  const statements=[
    db.prepare(
      "INSERT INTO financial_owner_enrollments(owner_id,operator_id,challenge_id,key_fingerprint,payload_hash,created_at) " +
      "SELECT ?,?,?,?,?,? WHERE EXISTS(SELECT 1 FROM financial_owner_enrollment_challenges WHERE challenge_id=? AND owner_id=? AND operator_id=? AND consumed_at IS NULL AND expires_at>?)"
    ).bind(ownerId,operatorId,challengeId,fingerprint,payloadHash,ownerNow,challengeId,ownerId,operatorId,ownerNow),
    db.prepare("UPDATE financial_owner_enrollment_challenges SET consumed_at=? WHERE challenge_id=? AND owner_id=? AND operator_id=? AND consumed_at IS NULL AND expires_at>?")
      .bind(ownerNow,challengeId,ownerId,operatorId,ownerNow),
    ownerInsert,operatorInsert
  ];
  for(const agentId of agentIds) statements.push(db.prepare(
    "INSERT INTO financial_participants(participant_id,participant_type,status,owner_id,operator_id,created_at,updated_at) " +
    "SELECT ?,'agent','active',?,?,?,? WHERE EXISTS(SELECT 1 FROM financial_owner_enrollments WHERE owner_id=? AND payload_hash=?)"
  ).bind(agentId,ownerId,operatorId,ownerNow,ownerNow,ownerId,payloadHash));
  for(const currency of currencies) {
    for(const accountType of ["treasury","reserve","owner_payable","fee_expense","operating_expense"]) {
      statements.push(db.prepare(
        "INSERT INTO financial_accounts(account_id,owner_id,agent_id,account_type,currency,status,created_at,updated_at) " +
        "SELECT ?,?,NULL,?,?,'active',?,? WHERE EXISTS(SELECT 1 FROM financial_owner_enrollments WHERE owner_id=? AND payload_hash=?)"
      ).bind("acct-"+ownerId+"-"+accountType+"-"+currency,ownerId,accountType,currency,ownerNow,ownerNow,ownerId,payloadHash));
    }
    for(const agentId of agentIds) statements.push(db.prepare(
      "INSERT INTO financial_accounts(account_id,owner_id,agent_id,account_type,currency,status,created_at,updated_at) " +
      "SELECT ?,?,?, 'agent_operating',?,'active',?,? WHERE EXISTS(SELECT 1 FROM financial_owner_enrollments WHERE owner_id=? AND payload_hash=?)"
    ).bind("acct-"+agentId+"-agent-operating-"+currency,ownerId,agentId,currency,ownerNow,ownerNow,ownerId,payloadHash));
  }
  statements.push(db.prepare(
    "INSERT INTO financial_control_state(owner_id,emergency_paused,pause_reason,changed_by,changed_at) " +
    "SELECT ?,1,'New owner enrollment: spending remains paused',?,? WHERE EXISTS(SELECT 1 FROM financial_owner_enrollments WHERE owner_id=? AND payload_hash=?)"
  ).bind(ownerId,ownerId,ownerNow,ownerId,payloadHash));
  statements.push(db.prepare(
    "INSERT INTO financial_audit_events(event_id,owner_id,actor_id,event_type,target_type,target_id,request_id,details_json,created_at) " +
    "SELECT ?,?,?, 'financial.owner_enrolled','owner',?,?,?,? WHERE EXISTS(SELECT 1 FROM financial_owner_enrollments WHERE owner_id=? AND payload_hash=?)"
  ).bind(crypto.randomUUID(),ownerId,ownerId,ownerId,challengeId,json({operator_id:operatorId,agent_ids:agentIds,currencies}),ownerNow,ownerId,payloadHash));
  try {
    await db.batch(statements);
  } catch(error) {
    const enrolled=await db.prepare("SELECT owner_id,operator_id,challenge_id,key_fingerprint,payload_hash FROM financial_owner_enrollments WHERE owner_id=?")
      .bind(ownerId).first();
    if(enrolled&&enrolled.challenge_id===challengeId&&enrolled.key_fingerprint===fingerprint&&enrolled.payload_hash===payloadHash)
      return {ok:true,idempotent:true,owner_id:ownerId,operator_id:operatorId,agent_ids:agentIds};
    throw error;
  }
  const result=await db.prepare(
    "SELECT o.participant_id AS owner_id,s.participant_id AS operator_id,s.key_fingerprint " +
    "FROM financial_participants o JOIN financial_participants s ON s.owner_id=o.participant_id " +
    "WHERE o.participant_id=? AND o.participant_type='owner' AND s.participant_id=? AND s.participant_type='operator'"
  ).bind(ownerId,operatorId).first();
  if(!result||result.key_fingerprint!==fingerprint) return {ok:false,reason:"owner_enrollment_incomplete"};
  return {ok:true,created:true,owner_id:ownerId,operator_id:operatorId,agent_ids:agentIds,currencies,emergency_paused:true};
}

export async function getCloudFinancialControls(db, ownerId, { limit = 25 } = {}) {
  if (!validId(ownerId)) return { ok: false, reason: "invalid_owner_id" };
  const safeLimit = Number.isInteger(limit) ? Math.min(100, Math.max(1, limit)) : 25;
  const [control, agents, budgets, reservations, schedules, occurrences, policies] = await Promise.all([
    db.prepare("SELECT emergency_paused,pause_reason,changed_at FROM financial_control_state WHERE owner_id=?").bind(ownerId).first(),
    db.prepare("SELECT participant_id,status,operator_id FROM financial_participants WHERE owner_id=? AND participant_type='agent' ORDER BY participant_id").bind(ownerId).all(),
    db.prepare(
      "SELECT a.agent_id,a.currency," +
      "COALESCE((SELECT SUM(CASE WHEN p.direction='credit' THEN p.amount_minor ELSE -p.amount_minor END) FROM financial_journal_postings p WHERE p.account_id=a.account_id),0) AS allocated_minor," +
      "COALESCE((SELECT SUM(r.amount_minor) FROM financial_budget_reservations r WHERE r.agent_id=a.agent_id AND r.owner_id=a.owner_id AND r.currency=a.currency AND r.status='reserved' AND r.expires_at>strftime('%Y-%m-%dT%H:%M:%fZ','now')),0) AS reserved_minor " +
      "FROM financial_accounts a WHERE a.owner_id=? AND a.account_type='agent_operating' AND a.status='active' ORDER BY a.agent_id,a.currency"
    ).bind(ownerId).all(),
    db.prepare("SELECT reservation_id,agent_id,policy_id,policy_version,destination,currency,amount_minor,status,expires_at,created_at FROM financial_budget_reservations WHERE owner_id=? ORDER BY created_at DESC LIMIT ?").bind(ownerId,safeLimit).all(),
    db.prepare("SELECT schedule_id,agent_id,policy_id,policy_version,destination,currency,amount_minor,interval_seconds,next_due_at,status,created_at FROM financial_expense_schedules WHERE owner_id=? ORDER BY created_at DESC LIMIT ?").bind(ownerId,safeLimit).all(),
    db.prepare("SELECT occurrence_id,schedule_id,agent_id,due_at,status,reason_code,created_at,updated_at FROM financial_expense_occurrences WHERE owner_id=? ORDER BY created_at DESC LIMIT ?").bind(ownerId,safeLimit).all(),
    db.prepare("SELECT policy_id,version,agent_id,signer_id,currency,per_transaction_limit_minor,daily_spend_limit_minor,status,created_at FROM financial_policies WHERE owner_id=? ORDER BY created_at DESC LIMIT ?").bind(ownerId,safeLimit).all()
  ]);
  return {
    ok: true,
    emergency_paused: !control || control.emergency_paused !== 0,
    pause_reason: control?.pause_reason || "Cloud spending remains paused until the owner explicitly enables it.",
    pause_changed_at: control?.changed_at || null,
    agents: agents.results || [],
    budgets: (budgets.results || []).map(row=>({...row,available_minor:row.allocated_minor-row.reserved_minor})),
    reservations: reservations.results || [],
    schedules: schedules.results || [],
    policies: policies.results || [],
    occurrences: occurrences.results || [],
    source_of_truth: "Cloudflare D1",
    live_transfers_enabled: false
  };
}

export async function setCloudEmergencyPause(db, { ownerId, actorId, paused, reason, now = new Date().toISOString() }) {
  if (!validId(ownerId) || actorId !== ownerId || typeof paused !== "boolean") return { ok: false, reason: "owner_authorization_required" };
  const note = typeof reason === "string" && reason.trim() ? reason.trim().slice(0,240) : (paused ? "Owner emergency pause" : "Owner resumed cloud simulated spending");
  await db.batch([
    db.prepare(
      "INSERT INTO financial_control_state(owner_id,emergency_paused,pause_reason,changed_by,changed_at) " +
      "SELECT participant_id,?,?,participant_id,? FROM financial_participants " +
      "WHERE participant_id=? AND participant_type='owner' AND status='active' " +
      "ON CONFLICT(owner_id) DO UPDATE SET emergency_paused=excluded.emergency_paused,pause_reason=excluded.pause_reason,changed_by=excluded.changed_by,changed_at=excluded.changed_at"
    ).bind(paused ? 1 : 0,note,now,ownerId),
    db.prepare(
      "INSERT INTO financial_audit_events(event_id,owner_id,actor_id,event_type,target_type,target_id,request_id,details_json,created_at) " +
      "SELECT lower(hex(randomblob(16))),participant_id,participant_id,?,'financial_control_state',participant_id,?, ?,? " +
      "FROM financial_participants WHERE participant_id=? AND participant_type='owner' AND status='active'"
    ).bind(paused ? "financial.emergency_paused" : "financial.emergency_unpaused",crypto.randomUUID(),json({paused,reason:note}),now,ownerId)
  ]);
  const row = await db.prepare("SELECT emergency_paused FROM financial_control_state WHERE owner_id=?").bind(ownerId).first();
  if (!row || row.emergency_paused !== (paused ? 1 : 0)) return { ok: false, reason: "active_owner_not_found" };
  return { ok: true, emergency_paused: paused };
}

export async function reserveCloudAgentBudget(db, input, { now = new Date().toISOString() } = {}) {
  const { ownerId, agentId, reservationId, idempotencyKey, destination, currency, amountMinor, expiresAt } = input || {};
  if (![ownerId,agentId,reservationId].every(validId) || typeof idempotencyKey !== "string" ||
      !/^[A-Za-z0-9._:-]{8,128}$/.test(idempotencyKey) || typeof destination !== "string" ||
      !destination.trim() || destination.length > 256 || !/^[A-Z]{3}$/.test(currency) ||
      !Number.isSafeInteger(amountMinor) || amountMinor <= 0 || !iso(expiresAt) ||
      Date.parse(expiresAt) <= Date.parse(now) || Date.parse(expiresAt) > Date.parse(now) + 86400000) {
    return { ok: false, reason: "invalid_reservation" };
  }
  const policy = await loadActiveCloudFinancialPolicy(db,agentId);
  if (!policy.ok) return policy;
  if (policy.policy.owner_id !== ownerId || policy.policy.currency !== currency ||
      amountMinor > policy.policy.per_transaction_limit_minor ||
      !policy.policy.allowed_destinations.includes(destination)) return { ok: false, reason: "policy_denied" };
  const existing = await db.prepare("SELECT reservation_id,owner_id,agent_id,policy_id,policy_version,destination,currency,amount_minor,status FROM financial_budget_reservations WHERE idempotency_key=?").bind(idempotencyKey).first();
  if (existing) {
    const same = existing.owner_id===ownerId && existing.agent_id===agentId &&
      existing.policy_id===policy.policy.policy_id && existing.policy_version===policy.policy.version &&
      existing.destination===destination && existing.currency===currency && existing.amount_minor===amountMinor;
    return same ? { ok:true,idempotent:true,reservation_id:existing.reservation_id,status:existing.status } :
      { ok:false,reason:"idempotency_key_reused_with_different_terms" };
  }
  const signer = await db.prepare("SELECT signer_id FROM financial_policies WHERE policy_id=? AND version=? AND status='active'").bind(policy.policy.policy_id,policy.policy.version).first();
  if (!signer) return { ok:false,reason:"active_policy_not_found" };
  try {
    await db.batch([
      db.prepare(
        "INSERT INTO financial_budget_reservations(reservation_id,owner_id,agent_id,policy_id,policy_version,idempotency_key,destination,currency,amount_minor,status,expires_at,created_at,updated_at) " +
        "VALUES(?,?,?,?,?,?,?,?,?,'reserved',?,?,?)"
      ).bind(reservationId,ownerId,agentId,policy.policy.policy_id,policy.policy.version,idempotencyKey,destination,currency,amountMinor,expiresAt,now,now),
      db.prepare(
        "INSERT INTO financial_audit_events(event_id,owner_id,actor_id,event_type,target_type,target_id,request_id,details_json,created_at) VALUES(?,?,?,?,?,?,?,?,?)"
      ).bind(crypto.randomUUID(),ownerId,signer.signer_id,"financial.budget_reserved","budget_reservation",reservationId,idempotencyKey,
        json({agent_id:agentId,amount_minor:amountMinor,currency,destination,policy_version:policy.policy.version}),now)
    ]);
    return { ok:true,idempotent:false,reservation_id:reservationId,status:"reserved" };
  } catch(error) {
    const raced = await db.prepare("SELECT reservation_id,owner_id,agent_id,policy_id,policy_version,destination,currency,amount_minor,status FROM financial_budget_reservations WHERE idempotency_key=?").bind(idempotencyKey).first();
    if (raced && raced.owner_id===ownerId && raced.agent_id===agentId && raced.destination===destination &&
        raced.currency===currency && raced.amount_minor===amountMinor && raced.policy_id===policy.policy.policy_id &&
        raced.policy_version===policy.policy.version) return { ok:true,idempotent:true,reservation_id:raced.reservation_id,status:raced.status };
    const message = String(error?.message || "");
    if (/pause/i.test(message)) return { ok:false,reason:"emergency_paused" };
    if (/daily spend limit/i.test(message)) return { ok:false,reason:"daily_spend_limit_exceeded" };
    if (/insufficient available/i.test(message)) return { ok:false,reason:"insufficient_agent_budget" };
    if (/authorization/i.test(message)) return { ok:false,reason:"policy_or_participant_denied" };
    throw error;
  }
}

export async function settleCloudAgentExpense(db, { ownerId, actorId, reservationId, transactionId = crypto.randomUUID(), now = new Date().toISOString() }) {
  if (!validId(ownerId) || !validId(reservationId)) return { ok:false,reason:"invalid_expense" };
  const reservation = await db.prepare("SELECT * FROM financial_budget_reservations WHERE reservation_id=? AND owner_id=?").bind(reservationId,ownerId).first();
  if (!reservation) return { ok:false,reason:"reservation_not_found" };
  if (reservation.status === "settled") return { ok:true,idempotent:true,transaction_id:reservation.settled_transaction_id };
  if (reservation.status !== "reserved" || Date.parse(reservation.expires_at) <= Date.parse(now)) return { ok:false,reason:"reservation_not_active" };
  const verified = await loadActiveCloudFinancialPolicy(db,reservation.agent_id);
  if (!verified.ok || verified.policy.owner_id!==ownerId || verified.policy.policy_id!==reservation.policy_id ||
      verified.policy.version!==reservation.policy_version || !verified.policy.allowed_destinations.includes(reservation.destination) ||
      reservation.amount_minor>verified.policy.per_transaction_limit_minor) return { ok:false,reason:"policy_no_longer_authorized" };
  const signer = await db.prepare("SELECT signer_id FROM financial_policies WHERE policy_id=? AND version=? AND status='active'").bind(reservation.policy_id,reservation.policy_version).first();
  const accounts = await db.prepare(
    "SELECT account_id,account_type FROM financial_accounts WHERE owner_id=? AND currency=? AND status='active' AND ((account_type='agent_operating' AND agent_id=?) OR (account_type='operating_expense' AND agent_id IS NULL))"
  ).bind(ownerId,reservation.currency,reservation.agent_id).all();
  const rows = accounts.results || [];
  const debit = rows.find(row=>row.account_type==="agent_operating");
  const credit = rows.find(row=>row.account_type==="operating_expense");
  if (!debit || !credit || !signer || (actorId && actorId!==signer.signer_id)) return { ok:false,reason:"expense_accounts_or_actor_unavailable" };
  const idem = "expense:"+reservationId;
  const payload = {owner_id:ownerId,agent_id:reservation.agent_id,reservation_id:reservationId,amount_minor:reservation.amount_minor,currency:reservation.currency,debit_account:debit.account_id,credit_account:credit.account_id};
  const hash = [...new Uint8Array(await crypto.subtle.digest("SHA-256",new TextEncoder().encode(json(payload))))].map(x=>x.toString(16).padStart(2,"0")).join("");
  const existing = await db.prepare("SELECT transaction_id,payload_hash FROM financial_journal_transactions WHERE idempotency_key=?").bind(idem).first();
  if (existing && existing.payload_hash!==hash) return {ok:false,reason:"expense_idempotency_conflict"};
  const statements = [];
  if (!existing) {
    statements.push(db.prepare(
      "INSERT INTO financial_journal_transactions(transaction_id,owner_id,idempotency_key,payload_hash,source_type,source_reference,currency,status,description,created_at) VALUES(?,?,?,?,'expense',?,?,'posted',?,?)"
    ).bind(transactionId,ownerId,idem,hash,reservationId,reservation.currency,"Authorized agent expense: "+reservation.destination,now));
    statements.push(db.prepare(
      "INSERT INTO financial_journal_postings(transaction_id,line_number,account_id,direction,amount_minor,currency,created_at) VALUES(?,1,?,'debit',?,?,?)"
    ).bind(transactionId,debit.account_id,reservation.amount_minor,reservation.currency,now));
    statements.push(db.prepare(
      "INSERT INTO financial_journal_postings(transaction_id,line_number,account_id,direction,amount_minor,currency,created_at) VALUES(?,2,?,'credit',?,?,?)"
    ).bind(transactionId,credit.account_id,reservation.amount_minor,reservation.currency,now));
    statements.push(db.prepare(
      "INSERT INTO financial_audit_events(event_id,owner_id,actor_id,event_type,target_type,target_id,request_id,details_json,created_at) VALUES(?,?,?,?,?,?,?,?,?)"
    ).bind(crypto.randomUUID(),ownerId,signer.signer_id,"financial.expense_journaled","journal_transaction",transactionId,idem,json(payload),now));
  }
  statements.push(db.prepare(
    "UPDATE financial_budget_reservations SET status='settled',settled_transaction_id=?,updated_at=? WHERE reservation_id=? AND owner_id=? AND status='reserved' AND expires_at>?"
  ).bind(existing?.transaction_id || transactionId,now,reservationId,ownerId,now));
  try {
    await db.batch(statements);
  } catch(error) {
    const row=await db.prepare("SELECT status,settled_transaction_id FROM financial_budget_reservations WHERE reservation_id=?").bind(reservationId).first();
    if(row?.status==="settled") return {ok:true,idempotent:true,transaction_id:row.settled_transaction_id};
    if(/pause/i.test(String(error?.message||""))) return {ok:false,reason:"emergency_paused"};
    if(/policy/i.test(String(error?.message||""))) return {ok:false,reason:"policy_no_longer_authorized"};
    throw error;
  }
  const result=await db.prepare("SELECT status,settled_transaction_id FROM financial_budget_reservations WHERE reservation_id=?").bind(reservationId).first();
  if(result?.status!=="settled") return {ok:false,reason:"reservation_settlement_not_committed"};
  return {ok:true,idempotent:!!existing,transaction_id:result.settled_transaction_id};
}

export async function createCloudExpenseSchedule(db, input, { now = new Date().toISOString() } = {}) {
  const { ownerId, agentId, scheduleId, destination, currency, amountMinor, intervalSeconds, nextDueAt } = input || {};
  if (![ownerId,agentId,scheduleId].every(validId) || typeof destination!=="string" ||
      !/^[A-Z]{3}$/.test(currency) || !Number.isSafeInteger(amountMinor) || amountMinor<=0 ||
      !Number.isInteger(intervalSeconds) || intervalSeconds<3600 || intervalSeconds>2678400 ||
      !iso(nextDueAt) || Date.parse(nextDueAt)<Date.parse(now)) return {ok:false,reason:"invalid_schedule"};
  const verified=await loadActiveCloudFinancialPolicy(db,agentId);
  if(!verified.ok) return verified;
  if(verified.policy.owner_id!==ownerId || verified.policy.currency!==currency ||
      amountMinor>verified.policy.per_transaction_limit_minor || !verified.policy.allowed_destinations.includes(destination))
    return {ok:false,reason:"policy_denied"};
  try {
    await db.batch([
      db.prepare(
        "INSERT INTO financial_expense_schedules(schedule_id,owner_id,agent_id,policy_id,policy_version,destination,currency,amount_minor,interval_seconds,next_due_at,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,'active',?,?)"
      ).bind(scheduleId,ownerId,agentId,verified.policy.policy_id,verified.policy.version,destination,currency,amountMinor,intervalSeconds,nextDueAt,now,now),
      db.prepare(
        "INSERT INTO financial_audit_events(event_id,owner_id,actor_id,event_type,target_type,target_id,request_id,details_json,created_at) VALUES(?,?,?,?,?,?,?,?,?)"
      ).bind(crypto.randomUUID(),ownerId,ownerId,"financial.expense_schedule_created","expense_schedule",scheduleId,scheduleId,
        json({agent_id:agentId,destination,currency,amount_minor:amountMinor,interval_seconds:intervalSeconds,policy_version:verified.policy.version}),now)
    ]);
    return {ok:true,schedule_id:scheduleId,status:"active",policy_version:verified.policy.version};
  } catch(error) {
    if(/schedule is not authorized/i.test(String(error?.message||""))) return {ok:false,reason:"policy_denied"};
    throw error;
  }
}

export async function setCloudExpenseScheduleStatus(db, { ownerId, scheduleId, status, now = new Date().toISOString() }) {
  if(!validId(ownerId)||!validId(scheduleId)||!["active","paused","cancelled"].includes(status)) return {ok:false,reason:"invalid_schedule_control"};
  await db.batch([
    db.prepare(
      "UPDATE financial_expense_schedules SET status=?,updated_at=? WHERE owner_id=? AND schedule_id=? " +
      "AND EXISTS (SELECT 1 FROM financial_participants p WHERE p.participant_id=? AND p.participant_type='owner' AND p.status='active') " +
      "AND (?!='active' OR EXISTS (SELECT 1 FROM financial_policies fp WHERE fp.policy_id=financial_expense_schedules.policy_id AND fp.version=financial_expense_schedules.policy_version AND fp.status='active'))"
    ).bind(status,now,ownerId,scheduleId,ownerId,status),
    db.prepare(
      "INSERT INTO financial_audit_events(event_id,owner_id,actor_id,event_type,target_type,target_id,request_id,details_json,created_at) " +
      "SELECT lower(hex(randomblob(16))),participant_id,participant_id,?,'expense_schedule',?,?,?,? FROM financial_participants " +
      "WHERE participant_id=? AND participant_type='owner' AND status='active' " +
      "AND EXISTS (SELECT 1 FROM financial_expense_schedules WHERE owner_id=? AND schedule_id=?)"
    ).bind("financial.expense_schedule_"+status,scheduleId,scheduleId,json({status}),now,ownerId,ownerId,scheduleId)
  ]);
  const row=await db.prepare("SELECT status FROM financial_expense_schedules WHERE owner_id=? AND schedule_id=?").bind(ownerId,scheduleId).first();
  if(row?.status!==status) return {ok:false,reason:"schedule_not_found_or_policy_inactive"};
  return {ok:true,schedule_id:scheduleId,status};
}
async function stableId(value) {
  const digest=await crypto.subtle.digest("SHA-256",new TextEncoder().encode(value));
  return [...new Uint8Array(digest)].map(x=>x.toString(16).padStart(2,"0")).join("");
}

export async function runDueCloudExpenseSchedules(db, ownerId, { now = new Date().toISOString(), limit = 10 } = {}) {
  if(!validId(ownerId)) return {settled:0,blocked:0,skipped:0};
  const expiry=await expireCloudBudgetReservations(db,ownerId,{now});
  const control=await db.prepare("SELECT emergency_paused FROM financial_control_state WHERE owner_id=?").bind(ownerId).first();
  if(!control || control.emergency_paused!==0) return {settled:0,blocked:0,skipped:0,expired:expiry.expired,paused:true};
  const rows=await db.prepare(
    "SELECT schedule_id,agent_id,policy_id,policy_version,destination,currency,amount_minor,interval_seconds,next_due_at " +
    "FROM financial_expense_schedules WHERE owner_id=? AND status='active' AND next_due_at<=? ORDER BY next_due_at,schedule_id LIMIT ?"
  ).bind(ownerId,now,Math.min(25,Math.max(1,limit))).all();
  let settled=0,blocked=0,skipped=0;
  for(const schedule of rows.results||[]) {
    const dueAt=schedule.next_due_at;
    const key="schedule:"+await stableId(schedule.schedule_id+"|"+dueAt);
    const occurrenceId="occ-"+(await stableId(key)).slice(0,48);
    const retryWindow=Math.floor(Date.parse(now)/3600000);
    const reservationAttemptKey=key+":reservation:"+retryWindow;
    const reservationId="rsv-"+(await stableId(reservationAttemptKey)).slice(0,48);
    await db.prepare(
      "INSERT OR IGNORE INTO financial_expense_occurrences(occurrence_id,schedule_id,owner_id,agent_id,policy_id,policy_version,due_at,idempotency_key,status,created_at,updated_at) " +
      "SELECT ?,schedule_id,owner_id,agent_id,policy_id,policy_version,next_due_at,?,'claimed',?,? FROM financial_expense_schedules " +
      "WHERE schedule_id=? AND owner_id=? AND status='active' AND next_due_at=?"
    ).bind(occurrenceId,key,now,now,schedule.schedule_id,ownerId,dueAt).run();
    const occurrence=await db.prepare("SELECT occurrence_id,status FROM financial_expense_occurrences WHERE schedule_id=? AND due_at=?").bind(schedule.schedule_id,dueAt).first();
    if(!occurrence || occurrence.status==="settled" || occurrence.status==="skipped") { skipped++; continue; }
    const reservation=await reserveCloudAgentBudget(db,{
      ownerId,agentId:schedule.agent_id,reservationId,idempotencyKey:reservationAttemptKey,
      destination:schedule.destination,currency:schedule.currency,amountMinor:schedule.amount_minor,
      expiresAt:new Date(Date.parse(now)+3600000).toISOString()
    },{now});
    if(!reservation.ok) {
      await db.prepare("UPDATE financial_expense_occurrences SET status='blocked',reason_code=?,updated_at=? WHERE occurrence_id=? AND status!='settled'")
        .bind(reservation.reason,now,occurrence.occurrence_id).run();
      blocked++; continue;
    }
    await db.prepare("UPDATE financial_expense_occurrences SET status='reserved',reservation_id=?,reason_code=NULL,updated_at=? WHERE occurrence_id=? AND status!='settled'")
      .bind(reservation.reservation_id,now,occurrence.occurrence_id).run();
    const expense=await settleCloudAgentExpense(db,{ownerId,reservationId:reservation.reservation_id,now});
    if(!expense.ok) {
      await db.prepare("UPDATE financial_expense_occurrences SET status='blocked',reason_code=?,updated_at=? WHERE occurrence_id=? AND status!='settled'")
        .bind(expense.reason,now,occurrence.occurrence_id).run();
      blocked++; continue;
    }
    const nextDue=new Date(Date.parse(dueAt)+schedule.interval_seconds*1000).toISOString();
    await db.batch([
      db.prepare("UPDATE financial_expense_occurrences SET status='settled',reason_code=NULL,updated_at=? WHERE occurrence_id=? AND status='reserved'")
        .bind(now,occurrence.occurrence_id),
      db.prepare("UPDATE financial_expense_schedules SET next_due_at=?,updated_at=? WHERE schedule_id=? AND owner_id=? AND status='active' AND next_due_at=?")
        .bind(nextDue,now,schedule.schedule_id,ownerId,dueAt)
    ]);
    settled++;
  }
  return {settled,blocked,skipped,expired:expiry.expired};
}

export async function expireCloudBudgetReservations(db, ownerId, { now = new Date().toISOString() } = {}) {
  if(!validId(ownerId)) return {expired:0};
  const result=await db.batch([
    db.prepare(
      "INSERT INTO financial_audit_events(event_id,owner_id,actor_id,event_type,target_type,target_id,request_id,details_json,created_at) " +
      "SELECT lower(hex(randomblob(16))),r.owner_id,r.owner_id,'financial.reservation_expired','budget_reservation',r.reservation_id,r.idempotency_key," +
      "json_object('amount_minor',r.amount_minor,'currency',r.currency),? FROM financial_budget_reservations r " +
      "JOIN financial_participants o ON o.participant_id=r.owner_id AND o.participant_type='owner' AND o.status='active' " +
      "WHERE r.owner_id=? AND r.status='reserved' AND r.expires_at<=?"
    ).bind(now,ownerId,now),
    db.prepare(
      "UPDATE financial_budget_reservations SET status='expired',updated_at=? WHERE owner_id=? AND status='reserved' AND expires_at<=?"
    ).bind(now,ownerId,now)
  ]);
  return {expired:result?.[1]?.meta?.changes || 0};
}

export async function registerCloudSignedFinancialPolicy(db, { ownerId, policy, canonicalPayload, signatureBase64Url, signerKeyFingerprint, now = new Date().toISOString() }) {
  if(!validId(ownerId) || !policy || policy.owner_id!==ownerId) return {ok:false,reason:"owner_policy_mismatch"};
  const relationship=await db.prepare(
    "SELECT o.participant_id AS owner_id,o.participant_type AS owner_type,o.status AS owner_status," +
    "s.participant_id AS signer_id,s.participant_type AS signer_type,s.status AS signer_status,s.owner_id AS signer_owner_id,s.key_fingerprint,s.public_key_jwk," +
    "a.participant_id AS agent_id,a.participant_type AS agent_type,a.status AS agent_status,a.owner_id AS agent_owner_id,a.operator_id " +
    "FROM financial_participants o JOIN financial_participants a ON a.participant_id=? " +
    "JOIN financial_participants s ON s.participant_id=a.operator_id WHERE o.participant_id=?"
  ).bind(policy.agent_id,ownerId).first();
  if(!relationship) return {ok:false,reason:"owner_operator_agent_not_provisioned"};
  let signerJwk;
  try { signerJwk=JSON.parse(relationship.public_key_jwk); } catch { return {ok:false,reason:"signer_public_key_invalid"}; }
  const verification=await verifyOwnerSignedFinancialPolicy({
    policy,canonicalPayload,signatureBase64Url,signerKeyFingerprint,signerJwk,
    owner:{participant_id:relationship.owner_id,participant_type:relationship.owner_type,status:relationship.owner_status},
    signer:{participant_id:relationship.signer_id,participant_type:relationship.signer_type,status:relationship.signer_status,owner_id:relationship.signer_owner_id,key_fingerprint:relationship.key_fingerprint},
    agent:{participant_id:relationship.agent_id,participant_type:relationship.agent_type,status:relationship.agent_status,owner_id:relationship.agent_owner_id,operator_id:relationship.operator_id}
  });
  if(!verification.ok) return {ok:false,reason:verification.reason};
  const latest=await db.prepare("SELECT MAX(version) AS version FROM financial_policies WHERE policy_id=? AND owner_id=? AND agent_id=?")
    .bind(policy.policy_id,ownerId,policy.agent_id).first();
  if((latest?.version||0)>=policy.version) return {ok:false,reason:"policy_version_must_increase"};
  const destinations=json(policy.allowed_destinations);
  try {
    await db.batch([
      db.prepare("UPDATE financial_policies SET status='superseded',updated_at=? WHERE policy_id=? AND owner_id=? AND agent_id=? AND status='active'")
        .bind(now,policy.policy_id,ownerId,policy.agent_id),
      db.prepare(
        "INSERT INTO financial_policies(policy_id,version,owner_id,agent_id,signer_id,currency,per_transaction_limit_minor,daily_spend_limit_minor,allowed_destinations_json,canonical_payload,signature_base64url,signer_key_fingerprint,status,created_at,updated_at) " +
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,'active',?,?)"
      ).bind(policy.policy_id,policy.version,ownerId,policy.agent_id,relationship.signer_id,policy.currency,
        policy.per_transaction_limit_minor,policy.daily_spend_limit_minor,destinations,canonicalPayload,signatureBase64Url,signerKeyFingerprint,now,now),
      db.prepare(
        "INSERT INTO financial_audit_events(event_id,owner_id,actor_id,event_type,target_type,target_id,request_id,details_json,created_at) VALUES(?,?,?,?,?,?,?,?,?)"
      ).bind(crypto.randomUUID(),ownerId,relationship.signer_id,"financial.policy_registered","financial_policy",policy.policy_id,
        policy.policy_id,json({version:policy.version,agent_id:policy.agent_id,currency:policy.currency}),now)
    ]);
  } catch(error) {
    if(/monotonically|unique|active/i.test(String(error?.message||""))) return {ok:false,reason:"policy_version_conflict"};
    throw error;
  }
  return {ok:true,policy_id:policy.policy_id,version:policy.version,agent_id:policy.agent_id,signer_id:relationship.signer_id};
}

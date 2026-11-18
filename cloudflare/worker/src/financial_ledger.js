const SOURCE_TYPES = new Set(["settlement","allocation","expense","adjustment","reversal"]);
const ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:-]{2,79}$/;

function sortedJson(value) {
  if (Array.isArray(value)) return value.map(sortedJson);
  if (value && typeof value === "object") return Object.keys(value).sort().reduce((out,key)=>{out[key]=sortedJson(value[key]);return out;},{});
  return value;
}
function canonical(value) { return JSON.stringify(sortedJson(value)); }
async function sha256Hex(value) {
  const digest=await crypto.subtle.digest("SHA-256",new TextEncoder().encode(value));
  return [...new Uint8Array(digest)].map(byte=>byte.toString(16).padStart(2,"0")).join("");
}
export function validateCloudJournalCommand(command) {
  if(!command||typeof command!=="object"||Array.isArray(command)) return "invalid_command";
  for(const key of ["owner_id","actor_id"]) if(typeof command[key]!=="string"||!ID_PATTERN.test(command[key])) return "invalid_participant_id";
  if(typeof command.idempotency_key!=="string"||command.idempotency_key.length<8||command.idempotency_key.length>128||!/^[A-Za-z0-9._:-]+$/.test(command.idempotency_key)) return "invalid_idempotency_key";
  if(!SOURCE_TYPES.has(command.source_type)) return "invalid_source_type";
  if(typeof command.source_reference!=="string"||!command.source_reference.trim()||command.source_reference.length>160) return "invalid_source_reference";
  if(typeof command.currency!=="string"||!/^[A-Z]{3}$/.test(command.currency)) return "invalid_currency";
  if(typeof command.description!=="string"||!command.description.trim()||command.description.length>200) return "invalid_description";
  if(!Array.isArray(command.postings)||command.postings.length<2||command.postings.length>50) return "invalid_postings";
  const accounts=new Set();
  let debits=0,credits=0;
  for(const posting of command.postings) {
    if(!posting||typeof posting!=="object"||Array.isArray(posting)) return "invalid_posting";
    if(typeof posting.account_id!=="string"||!ID_PATTERN.test(posting.account_id)) return "invalid_account_id";
    if(accounts.has(posting.account_id)) return "duplicate_posting_account";
    accounts.add(posting.account_id);
    if(posting.direction!=="debit"&&posting.direction!=="credit") return "invalid_posting_direction";
    if(!Number.isSafeInteger(posting.amount_minor)||posting.amount_minor<=0) return "invalid_posting_amount";
    if(posting.direction==="debit") debits+=posting.amount_minor; else credits+=posting.amount_minor;
    if(!Number.isSafeInteger(debits)||!Number.isSafeInteger(credits)) return "posting_total_overflow";
  }
  if(debits!==credits) return "unbalanced_journal_transaction";
  return null;
}
async function existingByIdempotency(db,key) {
  return db.prepare("SELECT transaction_id,payload_hash,status FROM financial_journal_transactions WHERE idempotency_key=?")
    .bind(key).first();
}
export async function postCloudJournalTransaction(db,command,{now=new Date().toISOString(),transactionId=crypto.randomUUID(),eventId=crypto.randomUUID()}={}) {
  const invalid=validateCloudJournalCommand(command);
  if(invalid) return {ok:false,reason:invalid};
  const normalized={
    owner_id:command.owner_id,actor_id:command.actor_id,idempotency_key:command.idempotency_key,
    source_type:command.source_type,source_reference:command.source_reference,
    currency:command.currency,description:command.description,
    postings:command.postings.map(p=>({account_id:p.account_id,direction:p.direction,amount_minor:p.amount_minor}))
  };
  const payloadHash=await sha256Hex(canonical(normalized));
  const existing=await existingByIdempotency(db,command.idempotency_key);
  if(existing) return existing.payload_hash===payloadHash
    ? {ok:true,idempotent:true,transaction_id:existing.transaction_id}
    : {ok:false,reason:"idempotency_key_reused_with_different_terms"};
  const placeholders=command.postings.map(()=>"?").join(",");
  const accountRows=await db.prepare(
    "SELECT account_id,owner_id,currency,status FROM financial_accounts WHERE account_id IN ("+placeholders+")"
  ).bind(...command.postings.map(p=>p.account_id)).all();
  const accounts=accountRows?.results||[];
  if(accounts.length!==command.postings.length) return {ok:false,reason:"journal_account_not_found"};
  const byId=new Map(accounts.map(account=>[account.account_id,account]));
  for(const posting of command.postings) {
    const account=byId.get(posting.account_id);
    if(!account||account.owner_id!==command.owner_id||account.currency!==command.currency||account.status!=="active") {
      return {ok:false,reason:"journal_account_not_authorized"};
    }
  }
  const statements=[
    db.prepare("INSERT INTO financial_journal_transactions (transaction_id,owner_id,idempotency_key,payload_hash,source_type,source_reference,currency,status,description,created_at) VALUES (?,?,?,?,?,?,?,'posted',?,?)")
      .bind(transactionId,command.owner_id,command.idempotency_key,payloadHash,command.source_type,command.source_reference,command.currency,command.description,now),
    ...command.postings.map((posting,index)=>db.prepare(
      "INSERT INTO financial_journal_postings (transaction_id,line_number,account_id,direction,amount_minor,currency,created_at) VALUES (?,?,?,?,?,?,?)"
    ).bind(transactionId,index+1,posting.account_id,posting.direction,posting.amount_minor,command.currency,now)),
    db.prepare("INSERT INTO financial_audit_events (event_id,owner_id,actor_id,event_type,target_type,target_id,request_id,details_json,created_at) VALUES (?,?,?,?,?,?,?,?,?)")
      .bind(eventId,command.owner_id,command.actor_id,"journal.transaction_posted","journal_transaction",transactionId,command.idempotency_key,
        JSON.stringify({source_type:command.source_type,source_reference:command.source_reference,currency:command.currency,posting_count:command.postings.length}),now)
  ];
  try {
    await db.batch(statements);
    return {ok:true,idempotent:false,transaction_id:transactionId};
  } catch(error) {
    const raced=await existingByIdempotency(db,command.idempotency_key);
    if(raced) return raced.payload_hash===payloadHash
      ? {ok:true,idempotent:true,transaction_id:raced.transaction_id}
      : {ok:false,reason:"idempotency_key_reused_with_different_terms"};
    throw error;
  }
}

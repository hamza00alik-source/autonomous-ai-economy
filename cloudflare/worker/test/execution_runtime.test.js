import test from "node:test";
import assert from "node:assert/strict";
import { webcrypto, createHmac } from "node:crypto";
import worker from "../src/index.js";
import { createExecutionApprovalChallenge } from "../src/execution_approval.js";

if (!globalThis.crypto) Object.defineProperty(globalThis, "crypto", { value: webcrypto });

const bytes = new Uint8Array([80, 75, 3, 4, 1, 2, 3, 4]);
const hex = value => Buffer.from(value).toString("hex");
async function sha256(value) {
  return hex(await crypto.subtle.digest("SHA-256", value));
}

function fakeDb(publicKeyJwk) {
  const state = { job: null, events: [], consumed: new Set() };
  return {
    state,
    prepare(sql) {
      let values = [];
      return {
        bind(...args) { values = args; return this; },
        async first() {
          if (sql.includes("FROM financial_participants")) return { participant_id: "owner-001", public_key_jwk: JSON.stringify(publicKeyJwk) };
          if (sql.startsWith("SELECT job_id,status,artifact_sha256")) {
            if (state.job && state.job.job_id === values[0] && state.job.owner_id === values[1]) return {
              job_id: state.job.job_id, status: state.job.status, artifact_sha256: state.job.artifact_sha256,
              artifact_size_bytes: state.job.artifact_size_bytes, error_code: state.job.error_code,
              created_at: state.job.created_at, updated_at: state.job.updated_at
            };
            return null;
          }
          if (sql.startsWith("SELECT artifact_key,artifact_sha256")) {
            if (state.job && state.job.job_id === values[0] && state.job.owner_id === values[1]) return state.job;
            return null;
          }
          if (sql.includes("attempt_count < 3") || sql.includes("WHERE status='approved'")) {
            const leaseExpired = state.job?.status === "running" && Date.parse(state.job.lease_expires_at || "") < Date.parse(values[1]);
            return state.job && (state.job.status === "approved" || leaseExpired)
              ? { job_id: state.job.job_id, owner_id: state.job.owner_id, execution_spec_json: JSON.stringify({kind:"moba_objective_props_v1"}), attempt_count: state.job.attempt_count || 0 }
              : null;
          }
          if (sql.startsWith("SELECT job_id,status,artifact_key")) {
            if (state.job && state.job.owner_id === values[0] && state.job.idempotency_key === values[1]) return state.job;
            return null;
          }
          if (sql.startsWith("UPDATE internal_execution_jobs") && sql.includes("RETURNING job_id")) {
            if (state.job?.job_id === values[2] && (state.job.status === "approved" || state.job.status === "running")) {
              state.job.status = "running";
              state.job.lease_expires_at = values[0];
              state.job.updated_at = values[1];
              state.job.attempt_count = (state.job.attempt_count || 0) + 1;
              return { job_id: state.job.job_id };
            }
            return null;
          }
          return null;
        },
        async run() {
          if (sql.startsWith("INSERT INTO internal_execution_approval_nonces")) {
            const nonceKey = values[0] + ":" + values[1];
            if (state.consumed.has(nonceKey)) throw new Error("UNIQUE constraint failed");
            state.consumed.add(nonceKey);
            return { success: true };
          }
          if (sql.startsWith("INSERT OR IGNORE INTO internal_execution_jobs")) {
            if (!state.job) {
              state.job = {
                job_id: values[0], owner_id: values[1], idempotency_key: values[2],
                status: "approved", artifact_key: null, artifact_sha256: null,
                artifact_size_bytes: null, updated_at: values[5]
              };
            }
            return { success: true };
          }
          if (sql.startsWith("UPDATE internal_execution_jobs SET status='delivery_ready'")) {
            Object.assign(state.job, {
              status: "delivery_ready", artifact_key: values[0],
              artifact_sha256: values[1], artifact_size_bytes: values[2], updated_at: values[3]
            });
            return { success: true };
          }
          if (sql.startsWith("UPDATE internal_execution_jobs SET status='failed'")) {
            state.job.status = "failed";
            return { success: true };
          }
          if (sql.startsWith("INSERT INTO internal_execution_events")) {
            state.events.push({ sql, values });
            return { success: true };
          }
          return { success: true };
        }
      };
    }
  };
}

async function makeEnv() {
  const ownerKeys = await crypto.subtle.generateKey({ name: "Ed25519" }, true, ["sign", "verify"]);
  const publicKeyJwk = await crypto.subtle.exportKey("jwk", ownerKeys.publicKey);
  const DB = fakeDb(publicKeyJwk);
  const idempotencyKey = "internal-pack-v1";
  const challenge = await createExecutionApprovalChallenge(DB, { ownerId: "owner-001", idempotencyKey });
  const signature = await crypto.subtle.sign({ name: "Ed25519" }, ownerKeys.privateKey, new TextEncoder().encode(challenge.canonical_payload));
  const approvalBody = { idempotency_key: idempotencyKey, approval: { canonical_payload: challenge.canonical_payload, signature: Buffer.from(signature).toString("base64url") } };
  const stored = new Map();
  const digestPromise = sha256(bytes);
  const env = {
    AAE_QUEUE_TOKEN: "owner-token",
    AAE_OWNER_ID: "owner-001",
    AAE_EXECUTION_BRIDGE_SECRET: "a-test-bridge-secret-with-at-least-32-bytes",
    DB,
    EXECUTION_RUNTIME: {
      async fetch(request) {
        const raw = await request.text();
        const timestamp = request.headers.get("x-aae-execution-timestamp");
        const signature = request.headers.get("x-aae-execution-signature");
        assert.ok(Math.abs(Date.now() / 1000 - Number(timestamp)) <= 300);
        const expected = createHmac("sha256", env.AAE_EXECUTION_BRIDGE_SECRET)
          .update(timestamp + "\n" + raw).digest("hex");
        assert.equal(signature, expected);
        const payload = JSON.parse(raw);
        return new Response(bytes, {
          status: 200,
          headers: {
            "content-type": "application/zip",
            "x-aae-job-id": payload.job_id,
            "x-aae-qa": "passed",
            "x-aae-sha256": await digestPromise,
            "x-aae-size": String(bytes.byteLength)
          }
        });
      }
    },
    EXECUTION_ARTIFACTS: {
      async put(key, value, options) { stored.set(key, { value, options }); },
      async get(key) {
        const item = stored.get(key);
        if (!item) return null;
        return {
          customMetadata: item.options.customMetadata,
          arrayBuffer: async () => item.value,
          body: new Response(item.value).body
        };
      }
    }
  };
  return { env, DB, stored, approvalBody };
}

function downloadRequest(jobId, token = "owner-token") {
  return new Request("https://aae.example/v1/owner/internal-products/jobs/" + jobId + "/artifact", {
    method: "GET",
    headers: { authorization: "Bearer " + token }
  });
}

function statusRequest(jobId, token = "owner-token") {
  return new Request("https://aae.example/v1/owner/internal-products/jobs/" + jobId, { headers: { authorization: "Bearer " + token } });
}
function challengeRequest(body = { idempotency_key: "internal-pack-v1" }, token = "owner-token") {
  return new Request("https://aae.example/v1/owner/internal-products/moba-objective-props/approval-challenge", {
    method: "POST", headers: { authorization: "Bearer " + token, origin: "https://aae.example", "content-type": "application/json" }, body: JSON.stringify(body)
  });
}

function request(body = { idempotency_key: "internal-pack-v1" }, token = "owner-token") {
  return new Request("https://aae.example/v1/owner/internal-products/moba-objective-props/build", {
    method: "POST",
    headers: {
      authorization: "Bearer " + token,
      origin: "https://aae.example",
      "content-type": "application/json"
    },
    body: JSON.stringify(body)
  });
}

test("owner approval challenge returns a scoped canonical payload and public key only", async () => {
  const { env } = await makeEnv();
  const response = await worker.fetch(challengeRequest(), env);
  assert.equal(response.status, 200);
  const result = await response.json();
  assert.equal(result.payload.action, "execute_internal_product");
  assert.equal(result.payload.execution_spec.kind, "moba_objective_props_v1");
  assert.equal(result.payload.expires_at - result.payload.issued_at, 300);
  assert.equal(typeof result.canonical_payload, "string");
  assert.equal(typeof result.public_key_jwk.x, "string");
  assert.equal("d" in result.public_key_jwk, false);
});

test("internal product execution requires owner authentication before touching D1", async () => {
  let touched = false;
  const response = await worker.fetch(request(undefined, "wrong-token"), {
    AAE_QUEUE_TOKEN: "owner-token",
    DB: { prepare() { touched = true; throw new Error("must not query"); } }
  });
  assert.equal(response.status, 401);
  assert.equal(touched, false);
});

test("owner execution request rejects arbitrary fields and invalid idempotency keys", async () => {
  const { env, approvalBody } = await makeEnv();
  const extra = await worker.fetch(request({ ...approvalBody, spec: "arbitrary" }), env);
  assert.equal(extra.status, 400);
  const malformed = await worker.fetch(request({ ...approvalBody, idempotency_key: "x" }), env);
  assert.equal(malformed.status, 400);
});

test("owner-approved product execution stores a verified private artifact and is idempotent", async () => {
  const { env, DB, stored, approvalBody } = await makeEnv();
  const first = await worker.fetch(request(approvalBody), env);
  assert.equal(first.status, 202);
  const queued = await first.json();
  assert.equal(queued.status, "approved");
  assert.equal(queued.queued, true);
  assert.equal(queued.published, false);
  assert.equal(queued.submitted, false);
  assert.equal(queued.customer_contacted, false);
  assert.equal(queued.sales_verified, false);
  assert.equal(DB.state.job.status, "approved");
  assert.equal(stored.size, 0);
  assert.equal(DB.state.events.length, 1);

  const second = await worker.fetch(request(approvalBody), env);
  assert.equal(second.status, 202);
  const repeated = await second.json();
  assert.equal(repeated.job_id, queued.job_id);
  assert.equal(repeated.idempotent, true);
  assert.equal(stored.size, 0);

  const scheduledPromises = [];
  await worker.scheduled({}, env, { waitUntil(promise) { scheduledPromises.push(promise); } });
  await Promise.all(scheduledPromises);
  assert.equal(DB.state.job.status, "delivery_ready");
  assert.equal(stored.size, 1);
  assert.equal(DB.state.events.length, 3);

  const result = { job_id: queued.job_id };
  const statusResponse = await worker.fetch(statusRequest(result.job_id), env);
  assert.equal(statusResponse.status, 200);
  const status = await statusResponse.json();
  assert.equal(status.status, "delivery_ready");
  assert.equal(status.artifact_sha256, await sha256(bytes));
  const download = await worker.fetch(downloadRequest(result.job_id), env);
  assert.equal(download.status, 200);
  assert.equal(download.headers.get("content-type"), "application/zip");
  assert.match(download.headers.get("content-disposition"), /moba-objective-props\.zip/);
  assert.deepEqual(new Uint8Array(await download.arrayBuffer()), bytes);
});

test("scheduled worker reclaims an expired execution lease within the retry budget", async () => {
  const { env, DB, approvalBody } = await makeEnv();
  const queuedResponse = await worker.fetch(request(approvalBody), env);
  assert.equal(queuedResponse.status, 202);
  DB.state.job.status = "running";
  DB.state.job.attempt_count = 1;
  DB.state.job.lease_expires_at = new Date(Date.now() - 60_000).toISOString();
  const scheduledPromises = [];
  await worker.scheduled({}, env, { waitUntil(promise) { scheduledPromises.push(promise); } });
  await Promise.all(scheduledPromises);
  assert.equal(DB.state.job.status, "delivery_ready");
  assert.equal(DB.state.job.attempt_count, 2);
});
test("private artifact download requires the owner bearer token", async () => {
  const { env } = await makeEnv();
  const response = await worker.fetch(downloadRequest("123e4567-e89b-42d3-a456-426614174000", "wrong-token"), env);
  assert.equal(response.status, 401);
});

test("execution fails closed when private runtime bindings are missing", async () => {
  const { env, approvalBody } = await makeEnv();
  delete env.EXECUTION_RUNTIME;
  const response = await worker.fetch(request(approvalBody), env);
  assert.equal(response.status, 503);
});


function inventoryRequest(path = "/v1/owner/internal-products/artifacts/inventory", token = "owner-token") {
  return new Request("https://aae.example" + path, { headers: { authorization: "Bearer " + token } });
}

test("private artifact inventory is read-only and reports orphan candidates and integrity warnings", async () => {
  const rows = [
    { artifact_key: "internal-products/job-1/moba-objective-props.zip", job_id: "job-1", owner_id: "owner-001", status: "delivery_ready", artifact_sha256: "abc", artifact_size_bytes: 8 },
    { artifact_key: "internal-products/job-2/moba-objective-props.zip", job_id: "job-2", owner_id: "owner-001", status: "failed", artifact_sha256: "def", artifact_size_bytes: 8 },
  ];
  let listCalls = 0;
  let deleteCalls = 0;
  const env = {
    AAE_QUEUE_TOKEN: "owner-token",
    AAE_OWNER_ID: "owner-001",
    DB: {
      prepare(sql) {
        assert.match(sql, /SELECT artifact_key,job_id,owner_id,status,artifact_sha256,artifact_size_bytes/);
        return { bind(...keys) {
          assert.equal(keys.length, 3);
          return { async all() { return { results: rows }; } };
        } };
      },
    },
    EXECUTION_ARTIFACTS: {
      async list(options) {
        listCalls++;
        assert.deepEqual(options, { prefix: "internal-products/", limit: 100 });
        return {
          objects: [
            { key: "internal-products/job-1/moba-objective-props.zip", size: 8, customMetadata: { job_id: "job-1", owner_id: "owner-001", sha256: "abc" } },
            { key: "internal-products/job-2/moba-objective-props.zip", size: 8, customMetadata: { job_id: "job-2", owner_id: "owner-001", sha256: "def" } },
            { key: "internal-products/orphan/moba-objective-props.zip", size: 12, uploaded: "2026-11-19T00:00:00.000Z" },
          ],
          truncated: true,
          cursor: "next-page-token",
        };
      },
      async delete() { deleteCalls++; throw new Error("inventory must never delete"); },
      async put() { throw new Error("inventory must never write"); },
    },
  };
  const response = await worker.fetch(inventoryRequest(), env);
  assert.equal(response.status, 200);
  const result = await response.json();
  assert.equal(result.mode, "dry_run_read_only");
  assert.equal(result.objects_scanned, 3);
  assert.equal(result.matched_d1_records, 2);
  assert.equal(result.orphan_candidate_count, 1);
  assert.equal(result.orphan_candidates[0].reason, "no_d1_artifact_record");
  assert.equal(result.orphan_candidates[0].action, "review_only");
  assert.equal(result.integrity_warning_count, 1);
  assert.deepEqual(result.integrity_warnings[0].reasons, ["job_not_delivery_ready"]);
  assert.equal(result.complete, false);
  assert.equal(result.next_cursor, "next-page-token");
  assert.equal(result.deletion_performed, false);
  assert.equal(result.metadata_modified, false);
  assert.equal(listCalls, 1);
  assert.equal(deleteCalls, 0);
});

test("private artifact inventory rejects invalid limits and fails closed without R2", async () => {
  const base = { AAE_QUEUE_TOKEN: "owner-token", AAE_OWNER_ID: "owner-001" };
  const invalid = await worker.fetch(inventoryRequest("/v1/owner/internal-products/artifacts/inventory?limit=1001"), base);
  assert.equal(invalid.status, 400);
  const missing = await worker.fetch(inventoryRequest(), base);
  assert.equal(missing.status, 503);
});

test("private artifact inventory requires owner bearer authentication", async () => {
  let touched = false;
  const response = await worker.fetch(inventoryRequest("/v1/owner/internal-products/artifacts/inventory", "wrong-token"), {
    AAE_QUEUE_TOKEN: "owner-token",
    get DB() { touched = true; throw new Error("must not access D1"); },
  });
  assert.equal(response.status, 401);
  assert.equal(touched, false);
});

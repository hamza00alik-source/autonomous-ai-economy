import test from "node:test";
import assert from "node:assert/strict";
import { webcrypto, createHmac } from "node:crypto";
import worker from "../src/index.js";

if (!globalThis.crypto) Object.defineProperty(globalThis, "crypto", { value: webcrypto });

const bytes = new Uint8Array([80, 75, 3, 4, 1, 2, 3, 4]);
const hex = value => Buffer.from(value).toString("hex");
async function sha256(value) {
  return hex(await crypto.subtle.digest("SHA-256", value));
}

function fakeDb() {
  const state = { job: null, events: [] };
  return {
    state,
    prepare(sql) {
      let values = [];
      return {
        bind(...args) { values = args; return this; },
        async first() {
          if (sql.includes("FROM financial_participants")) return { participant_id: "owner-001" };
          if (sql.startsWith("SELECT artifact_key,artifact_sha256")) {
            if (state.job && state.job.job_id === values[0] && state.job.owner_id === values[1]) return state.job;
            return null;
          }
          if (sql.startsWith("SELECT job_id,status,artifact_key")) {
            if (state.job && state.job.owner_id === values[0] && state.job.idempotency_key === values[1]) return state.job;
            return null;
          }
          if (sql.startsWith("UPDATE internal_execution_jobs") && sql.includes("RETURNING job_id")) {
            if (state.job?.job_id === values[1] && state.job.status === "approved") {
              state.job.status = "running";
              state.job.updated_at = values[0];
              return { job_id: state.job.job_id };
            }
            return null;
          }
          return null;
        },
        async run() {
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

function makeEnv() {
  const DB = fakeDb();
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
  return { env, DB, stored };
}

function downloadRequest(jobId, token = "owner-token") {
  return new Request("https://aae.example/v1/owner/internal-products/jobs/" + jobId + "/artifact", {
    method: "GET",
    headers: { authorization: "Bearer " + token }
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

test("internal product execution requires owner authentication before touching D1", async () => {
  let touched = false;
  const response = await worker.fetch(request(), {
    AAE_QUEUE_TOKEN: "owner-token",
    DB: { prepare() { touched = true; throw new Error("must not query"); } }
  });
  assert.equal(response.status, 401);
  assert.equal(touched, false);
});

test("owner execution request rejects arbitrary fields and invalid idempotency keys", async () => {
  const { env } = makeEnv();
  const extra = await worker.fetch(request({ idempotency_key: "internal-pack-v1", spec: "arbitrary" }), env);
  assert.equal(extra.status, 400);
  const malformed = await worker.fetch(request({ idempotency_key: "x" }), env);
  assert.equal(malformed.status, 400);
});

test("owner-approved product execution stores a verified private artifact and is idempotent", async () => {
  const { env, DB, stored } = makeEnv();
  const first = await worker.fetch(request(), env);
  assert.equal(first.status, 201);
  const result = await first.json();
  assert.equal(result.status, "delivery_ready");
  assert.equal(result.published, false);
  assert.equal(result.submitted, false);
  assert.equal(result.customer_contacted, false);
  assert.equal(result.sales_verified, false);
  assert.equal(DB.state.job.status, "delivery_ready");
  assert.equal(stored.size, 1);
  assert.equal(DB.state.events.length, 3);

  const second = await worker.fetch(request(), env);
  assert.equal(second.status, 200);
  const repeated = await second.json();
  assert.equal(repeated.job_id, result.job_id);
  assert.equal(repeated.idempotent, true);
  assert.equal(stored.size, 1);

  const download = await worker.fetch(downloadRequest(result.job_id), env);
  assert.equal(download.status, 200);
  assert.equal(download.headers.get("content-type"), "application/zip");
  assert.match(download.headers.get("content-disposition"), /moba-objective-props\\.zip/);
  assert.deepEqual(new Uint8Array(await download.arrayBuffer()), bytes);
});

test("execution fails closed when private runtime bindings are missing", async () => {
  const { env } = makeEnv();
  delete env.EXECUTION_RUNTIME;
  const response = await worker.fetch(request(), env);
  assert.equal(response.status, 503);
});

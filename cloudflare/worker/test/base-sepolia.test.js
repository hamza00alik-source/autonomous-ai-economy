import test from "node:test";
import assert from "node:assert/strict";
import { encodeAbiParameters, encodeEventTopics } from "viem";
import { privateKeyToAccount } from "viem/accounts";
import {
  BASE_MAINNET_CHAIN_ID,
  BASE_SEPOLIA_CHAIN_ID,
  BASE_SEPOLIA_USDC_ADDRESS,
  BASE_USDC_CHECKOUT_ABI,
  signBaseUsdcInvoice,
  recoverBaseUsdcInvoiceSigner,
  decodeBaseUsdcPaymentLog,
  createBasePublicClient,
  pollBaseUsdc,
} from "../src/base-usdc.js";

const KEY = "0x0123456789012345678901234567890123456789012345678901234567890123";
const signer = privateKeyToAccount(KEY);
const merchant = "0x1111111111111111111111111111111111111111";
const contract = "0x2222222222222222222222222222222222222222";
const orderIdHash = "0x" + "ab".repeat(32);

test("Base Sepolia invoice signature uses chain 84532 and recovers only in that domain", async () => {
  const deadline = Math.floor(Date.now() / 1000) + 600;
  const invoice = await signBaseUsdcInvoice({
    privateKey: KEY,
    expectedSignerAddress: signer.address,
    contractAddress: contract,
    merchantAddress: merchant,
    orderId: "sepolia-order-123",
    amountMinor: 5_000_000,
    deadline,
    chainId: BASE_SEPOLIA_CHAIN_ID,
  });
  assert.equal(invoice.chainId, BASE_SEPOLIA_CHAIN_ID);
  const recovered = await recoverBaseUsdcInvoiceSigner({
    orderIdHash: invoice.orderIdHash,
    amountMinor: invoice.amountMinor,
    deadline,
    merchantAddress: merchant,
    contractAddress: contract,
    signature: invoice.signature,
    chainId: BASE_SEPOLIA_CHAIN_ID,
  });
  assert.equal(recovered.toLowerCase(), signer.address.toLowerCase());
  const wrongDomainRecovery = await recoverBaseUsdcInvoiceSigner({
    orderIdHash: invoice.orderIdHash,
    amountMinor: invoice.amountMinor,
    deadline,
    merchantAddress: merchant,
    contractAddress: contract,
    signature: invoice.signature,
    chainId: BASE_MAINNET_CHAIN_ID,
  });
  assert.notEqual(wrongDomainRecovery.toLowerCase(), signer.address.toLowerCase());
});

test("Base Sepolia event decoder accepts only Circle's Sepolia USDC token and chain", () => {
  const buyer = "0x3333333333333333333333333333333333333333";
  const log = {
    address: contract,
    topics: encodeEventTopics({
      abi: BASE_USDC_CHECKOUT_ABI,
      eventName: "OrderPaid",
      args: { orderId: orderIdHash, buyer, merchant },
    }),
    data: encodeAbiParameters(
      [{ type: "uint256" }, { type: "address" }],
      [5_000_000n, BASE_SEPOLIA_USDC_ADDRESS],
    ),
    transactionHash: "0x" + "cd".repeat(32),
    blockHash: "0x" + "ef".repeat(32),
    blockNumber: 100n,
    logIndex: 0,
    removed: false,
  };
  const decoded = decodeBaseUsdcPaymentLog(log, {
    chainId: BASE_SEPOLIA_CHAIN_ID,
    contractAddress: contract,
    merchantAddress: merchant,
    orderIdHash,
    amountMinor: "5000000",
  });
  assert.equal(decoded.chainId, BASE_SEPOLIA_CHAIN_ID);
  assert.equal(decoded.tokenAddress, BASE_SEPOLIA_USDC_ADDRESS);
  assert.throws(() => decodeBaseUsdcPaymentLog(log, {
    chainId: BASE_MAINNET_CHAIN_ID,
    contractAddress: contract,
    merchantAddress: merchant,
    orderIdHash,
    amountMinor: "5000000",
  }), /token/);
  assert.throws(() => decodeBaseUsdcPaymentLog(log, {
    chainId: 1,
    contractAddress: contract,
    merchantAddress: merchant,
    orderIdHash,
    amountMinor: "5000000",
  }), /unsupported Base chain ID/);
});

test("Base Sepolia indexer selects testnet chain/token and refuses mainnet-token substitution", async () => {
  const cursor = { next_block: 100, last_block_hash: null, halted_at: null, halt_reason: null };
  const updates = [];
  const db = {
    prepare(sql) {
      return {
        values: [],
        bind(...values) { this.values = values; return this; },
        async first() { return sql.includes("SELECT next_block,last_block_hash") ? { ...cursor } : null; },
        async run() {
          updates.push({ sql, values: this.values });
          if (sql.startsWith("UPDATE base_usdc_indexer_state SET next_block")) {
            cursor.next_block = this.values[0];
          }
          return { meta: { changes: 1 } };
        },
      };
    },
    async batch() { throw new Error("unexpected D1 batch"); },
  };
  const rpcCalls = [];
  const client = {
    async getBlockNumber() { rpcCalls.push("head"); return 110n; },
    async getLogs(args) { rpcCalls.push(args); return []; },
    async getTransactionReceipt() { throw new Error("not expected"); },
    async getBlock({ blockNumber }) { rpcCalls.push(blockNumber.toString()); return { hash: "0x" + "ef".repeat(32) }; },
  };
  const env = {
    AAE_BASE_USDC_INDEXER_ENABLED: "true",
    BASE_CHAIN_ID: "84532",
    BASE_USDC_TOKEN_ADDRESS: BASE_SEPOLIA_USDC_ADDRESS,
    BASE_CHECKOUT_CONTRACT_ADDRESS: contract,
    BASE_MERCHANT_ADDRESS: merchant,
    BASE_DEPLOYMENT_BLOCK: "100",
    BASE_CONFIRMATIONS: "2",
    BASE_MAX_BLOCKS_PER_POLL: "20",
    DB: db,
  };
  const result = await pollBaseUsdc(env, client);
  assert.equal(result.enabled, true);
  assert.equal(result.scanned_from_block, 100);
  assert.equal(result.scanned_to_block, "109");
  assert.ok(rpcCalls.includes("head"));
  assert.equal(updates.at(-1).values[0], 110);
  await assert.rejects(() => pollBaseUsdc({
    ...env,
    BASE_USDC_TOKEN_ADDRESS: "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
  }, client), /does not match the selected Base network/);
});

test("Base public RPC client rejects unsupported chain IDs before creating transport", () => {
  assert.throws(() => createBasePublicClient("https://example.invalid", 1), /unsupported Base chain ID/);
  assert.throws(() => createBasePublicClient("http://example.invalid", BASE_SEPOLIA_CHAIN_ID), /HTTPS/);
});

test("Base Sepolia finalized payment event settles only into its testnet ledger", async () => {
  const buyer = "0x3333333333333333333333333333333333333333";
  const tx = "0x" + "cd".repeat(32);
  const blockHash = "0x" + "ef".repeat(32);
  const log = {
    address: contract,
    topics: encodeEventTopics({
      abi: BASE_USDC_CHECKOUT_ABI,
      eventName: "OrderPaid",
      args: { orderId: orderIdHash, buyer, merchant },
    }),
    data: encodeAbiParameters(
      [{ type: "uint256" }, { type: "address" }],
      [5_000_000n, BASE_SEPOLIA_USDC_ADDRESS],
    ),
    transactionHash: tx,
    blockHash,
    blockNumber: 123n,
    logIndex: 1,
    removed: false,
  };
  const invoice = {
    order_id: "sepolia-order-123",
    order_id_hash: orderIdHash,
    product_id: "moba-objective-props",
    agent_id: "game-asset-builder",
    amount_minor: 5_000_000,
    gross_amount_minor: 500,
    merchant_address: merchant,
    invoice_deadline: Math.floor(Date.now() / 1000) + 600,
    status: "pending",
    transaction_hash: null,
  };
  const db = {
    invoice,
    events: [],
    revenue: null,
    prepare(sql) {
      const self = this;
      return {
        values: [],
        bind(...values) { this.values = values; return this; },
        async first() {
          return sql.includes("FROM base_usdc_invoices WHERE order_id_hash=?") ? self.invoice : null;
        },
        async run() {
          if (sql.startsWith("INSERT INTO base_usdc_payment_events")) {
            const [chainId, transactionHash, logIndex, orderId, buyerAddress, merchantAddress, tokenAddress, amount, blockNumber, hash, , orderHash] = this.values;
            if (chainId !== BASE_SEPOLIA_CHAIN_ID || orderHash !== self.invoice.order_id_hash) return { meta: { changes: 0 } };
            self.events.push({ chain_id: chainId, transaction_hash: transactionHash, log_index: logIndex, order_id: orderId, buyer_address: buyerAddress, merchant_address: merchantAddress, token_address: tokenAddress, amount_minor: amount, block_number: blockNumber, block_hash: hash, transaction_status: "confirmed" });
            return { meta: { changes: 1 } };
          }
          if (sql.startsWith("UPDATE base_usdc_invoices SET status='settled'")) {
            const [buyerAddress, transactionHash, logIndex, blockNumber, hash, settledAt, expiresAt, updatedAt, orderHash, chainId, eventTx, eventLog] = this.values;
            const event = self.events.find(row => row.chain_id === chainId && row.transaction_hash === eventTx && row.log_index === eventLog);
            if (event && orderHash === self.invoice.order_id_hash && self.invoice.status === "pending") {
              Object.assign(self.invoice, { status: "settled", buyer_address: buyerAddress, transaction_hash: transactionHash, log_index: logIndex, block_number: blockNumber, block_hash: hash, settled_at: settledAt, download_expires_at: expiresAt, updated_at: updatedAt });
              return { meta: { changes: 1 } };
            }
            return { meta: { changes: 0 } };
          }
          if (sql.startsWith("INSERT OR IGNORE INTO base_usdc_agent_revenue_events")) {
            self.revenue = { crypto_received_amount: this.values[0], crypto_currency: "USDC", status: "settled_pending_reconciliation" };
            return { meta: { changes: 1 } };
          }
          return { meta: { changes: 0 } };
        }
      };
    },
    async batch(statements) {
      const results = [];
      for (const statement of statements) results.push(await statement.run());
      return results;
    }
  };
  const timestamp = Math.floor(Date.now() / 1000);
  const result = await (await import("../src/base-usdc.js")).settleBaseUsdcInvoice({
    db,
    log,
    finality: { confirmed: true, transactionHash: tx, blockHash, blockNumber: "123" },
    blockTimestamp: timestamp,
    contractAddress: contract,
    merchantAddress: merchant,
    tokenAddress: BASE_SEPOLIA_USDC_ADDRESS,
    chainId: BASE_SEPOLIA_CHAIN_ID,
  });
  assert.equal(result.status, "settled");
  assert.equal(db.events[0].chain_id, BASE_SEPOLIA_CHAIN_ID);
  assert.equal(db.invoice.status, "settled");
  assert.equal(db.revenue.status, "settled_pending_reconciliation");
  assert.equal(result.agent_credit_minor, null);
});

test("Base Sepolia checkpoint mismatch persistently halts and revokes testnet delivery", async () => {
  const cursor = { next_block: 200, last_block_hash: "0x" + "11".repeat(32), halted_at: null, halt_reason: null };
  const invoices = [{ status: "settled", download_expires_at: "future" }];
  const revenues = [{ status: "settled_pending_reconciliation" }];
  const db = {
    prepare(sql) {
      return {
        values: [],
        bind(...values) { this.values = values; return this; },
        async first() { return sql.includes("SELECT next_block,last_block_hash") ? { ...cursor } : null; },
        async run() { return { meta: { changes: 0 } }; },
        sql,
      };
    },
    async batch(statements) {
      for (const statement of statements) {
        if (statement.sql.startsWith("UPDATE base_usdc_invoices SET status='review'")) {
          for (const invoice of invoices) { invoice.status = "review"; invoice.download_expires_at = statement.values[0]; }
        }
        if (statement.sql.startsWith("UPDATE base_usdc_agent_revenue_events")) {
          for (const revenue of revenues) revenue.status = "refund_review";
        }
        if (statement.sql.startsWith("UPDATE base_usdc_indexer_state SET halted_at")) {
          cursor.halted_at = statement.values[0];
          cursor.halt_reason = statement.values[1];
        }
      }
      return [];
    },
  };
  const env = {
    AAE_BASE_USDC_INDEXER_ENABLED: "true",
    BASE_CHAIN_ID: String(BASE_SEPOLIA_CHAIN_ID),
    BASE_USDC_TOKEN_ADDRESS: BASE_SEPOLIA_USDC_ADDRESS,
    BASE_CHECKOUT_CONTRACT_ADDRESS: contract,
    BASE_MERCHANT_ADDRESS: merchant,
    BASE_DEPLOYMENT_BLOCK: "100",
    BASE_CONFIRMATIONS: "6",
    DB: db,
  };
  let rpcCalls = 0;
  const first = await pollBaseUsdc(env, {
    async getBlock() { rpcCalls += 1; return { hash: "0x" + "22".repeat(32) }; },
  });
  assert.equal(first.reorg_detected, true);
  assert.equal(first.halted, true);
  assert.equal(cursor.halt_reason, "checkpoint_hash_mismatch");
  assert.equal(invoices[0].status, "review");
  assert.equal(revenues[0].status, "refund_review");
  const before = rpcCalls;
  const second = await pollBaseUsdc(env, {
    async getBlock() { rpcCalls += 1; throw new Error("must remain halted"); },
  });
  assert.equal(second.halted, true);
  assert.equal(rpcCalls, before, "persistent halt must prevent all subsequent RPC scans");
});

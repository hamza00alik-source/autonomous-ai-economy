import test from "node:test";
import assert from "node:assert/strict";
import { encodeAbiParameters, encodeEventTopics } from "viem";
import { privateKeyToAccount } from "viem/accounts";
import {
  BASE_MAINNET_CHAIN_ID,
  BASE_USDC_ADDRESS,
  signBaseUsdcInvoice,
  recoverBaseUsdcInvoiceSigner,
  BASE_USDC_CHECKOUT_ABI,
  decodeBaseUsdcPaymentLog,
  verifyBaseUsdcFinality,
  createBasePublicClient,
  fetchConfirmedBaseUsdcLogs,
  settleBaseUsdcInvoice,
} from "../src/base-usdc.js";

const TEST_ONLY_PRIVATE_KEY = "0x0123456789012345678901234567890123456789012345678901234567890123";
const account = privateKeyToAccount(TEST_ONLY_PRIVATE_KEY);
const merchant = "0x1111111111111111111111111111111111111111";
const contract = "0x2222222222222222222222222222222222222222";

test("Base invoice signer creates a recoverable EIP-712 signature matching Solidity domain and struct", async () => {
  const deadline = Math.floor(Date.now() / 1000) + 600;
  const invoice = await signBaseUsdcInvoice({
    privateKey: TEST_ONLY_PRIVATE_KEY,
    expectedSignerAddress: account.address,
    contractAddress: contract,
    merchantAddress: merchant,
    orderId: "moba-test-order-123",
    amountMinor: 5_000_000,
    deadline,
  });
  assert.equal(invoice.chainId, BASE_MAINNET_CHAIN_ID);
  assert.equal(invoice.amountMinor, "5000000");
  assert.match(invoice.orderIdHash, /^0x[0-9a-f]{64}$/);
  assert.match(invoice.signature, /^0x[0-9a-f]{130}$/i);
  assert.equal(invoice.merchantAddress, merchant);
  assert.equal(invoice.contractAddress, contract);
  const recovered = await recoverBaseUsdcInvoiceSigner({
    orderIdHash: invoice.orderIdHash,
    amountMinor: invoice.amountMinor,
    deadline: invoice.deadline,
    merchantAddress: merchant,
    contractAddress: contract,
    signature: invoice.signature,
  });
  assert.equal(recovered.toLowerCase(), account.address.toLowerCase());
});

test("Base invoice signer refuses a key that does not match the configured signer address", async () => {
  await assert.rejects(() => signBaseUsdcInvoice({
    privateKey: TEST_ONLY_PRIVATE_KEY,
    expectedSignerAddress: merchant,
    contractAddress: contract,
    merchantAddress: merchant,
    orderId: "moba-test-order-123",
    amountMinor: 5_000_000,
    deadline: Math.floor(Date.now() / 1000) + 600,
  }), /does not match/);
});

test("Base invoice signer rejects wrong chain, invalid addresses, expired deadlines and unsafe amounts", async () => {
  const base = {
    privateKey: TEST_ONLY_PRIVATE_KEY,
    expectedSignerAddress: account.address,
    contractAddress: contract,
    merchantAddress: merchant,
    orderId: "moba-test-order-123",
    amountMinor: 5_000_000,
    deadline: Math.floor(Date.now() / 1000) + 600,
  };
  await assert.rejects(() => signBaseUsdcInvoice({ ...base, chainId: 1 }), /chain ID/);
  await assert.rejects(() => signBaseUsdcInvoice({ ...base, contractAddress: "not-an-address" }), /valid EVM address/);
  await assert.rejects(() => signBaseUsdcInvoice({ ...base, deadline: Math.floor(Date.now() / 1000) - 1 }), /future Unix timestamp/);
  await assert.rejects(() => signBaseUsdcInvoice({ ...base, amountMinor: 0 }), /positive uint256/);
  await assert.rejects(() => signBaseUsdcInvoice({ ...base, amountMinor: "not-a-number" }), /positive integer/);
});

test("native Base USDC contract constant matches Circle's canonical Base token", () => {
  assert.equal(BASE_USDC_ADDRESS.toLowerCase(), "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913");
});


test("Base OrderPaid decoder accepts only the exact invoice, merchant, token and contract", () => {
  const orderIdHash = "0x" + "ab".repeat(32);
  const buyer = "0x3333333333333333333333333333333333333333";
  const amount = 5_000_000n;
  const topics = encodeEventTopics({
    abi: BASE_USDC_CHECKOUT_ABI,
    eventName: "OrderPaid",
    args: {
      orderId: orderIdHash,
      buyer,
      merchant,
    },
  });
  const data = encodeAbiParameters(
    [{ type: "uint256", name: "amount" }, { type: "address", name: "token" }],
    [amount, BASE_USDC_ADDRESS],
  );
  const log = {
    address: contract,
    topics,
    data,
    transactionHash: "0x" + "cd".repeat(32),
    blockHash: "0x" + "ef".repeat(32),
    blockNumber: 123456n,
    logIndex: 2,
    removed: false,
  };
  const verified = decodeBaseUsdcPaymentLog(log, {
    chainId: BASE_MAINNET_CHAIN_ID,
    contractAddress: contract,
    merchantAddress: merchant,
    tokenAddress: BASE_USDC_ADDRESS,
    orderIdHash,
    amountMinor: "5000000",
  });
  assert.equal(verified.buyerAddress.toLowerCase(), buyer.toLowerCase());
  assert.equal(verified.amountMinor, "5000000");
  assert.equal(verified.transactionHash, log.transactionHash);
  assert.equal(verified.blockNumber, "123456");
  assert.equal(verified.logIndex, 2);

  assert.throws(() => decodeBaseUsdcPaymentLog(log, {
    chainId: BASE_MAINNET_CHAIN_ID,
    contractAddress: contract,
    merchantAddress: merchant,
    tokenAddress: BASE_USDC_ADDRESS,
    orderIdHash,
    amountMinor: "4999999",
  }), /amount does not exactly match/);
  assert.throws(() => decodeBaseUsdcPaymentLog({ ...log, address: merchant }, {
    chainId: BASE_MAINNET_CHAIN_ID,
    contractAddress: contract,
    merchantAddress: merchant,
    tokenAddress: BASE_USDC_ADDRESS,
    orderIdHash,
    amountMinor: "5000000",
  }), /emitter/);
  assert.throws(() => decodeBaseUsdcPaymentLog(log, {
    chainId: 1,
    contractAddress: contract,
    merchantAddress: merchant,
    tokenAddress: BASE_USDC_ADDRESS,
    orderIdHash,
    amountMinor: "5000000",
  }), /chain ID/);
});

test("Base OrderPaid decoder rejects removed logs and malformed coordinates", () => {
  const base = {
    chainId: BASE_MAINNET_CHAIN_ID,
    contractAddress: contract,
    merchantAddress: merchant,
    tokenAddress: BASE_USDC_ADDRESS,
    orderIdHash: "0x" + "ab".repeat(32),
    amountMinor: "5000000",
  };
  assert.throws(() => decodeBaseUsdcPaymentLog({ removed: true }, base), /removed or malformed/);
  assert.throws(() => decodeBaseUsdcPaymentLog({
    address: contract,
    transactionHash: "bad",
    blockHash: "0x" + "ef".repeat(32),
    blockNumber: 1n,
    logIndex: 0,
    data: "0x",
    topics: [],
  }, base), /canonical transaction/);
});


test("Base payment finality requires successful canonical receipt and configured confirmations", () => {
  const log = {
    transactionHash: "0x" + "cd".repeat(32),
    blockHash: "0x" + "ef".repeat(32),
    blockNumber: 100n,
  };
  const receipt = {
    status: "success",
    transactionHash: log.transactionHash,
    blockHash: log.blockHash,
    blockNumber: log.blockNumber,
  };
  const block = { hash: log.blockHash, number: log.blockNumber };
  const confirmed = verifyBaseUsdcFinality({
    log, receipt, block, headBlock: 105n, confirmations: 6,
  });
  assert.equal(confirmed.confirmed, true);
  assert.equal(confirmed.confirmations, 6);
  assert.throws(() => verifyBaseUsdcFinality({
    log, receipt, block, headBlock: 104n, confirmations: 6,
  }), /confirmation depth/);
  assert.throws(() => verifyBaseUsdcFinality({
    log, receipt: { ...receipt, status: "reverted" }, block, headBlock: 105n, confirmations: 6,
  }), /did not succeed/);
  assert.throws(() => verifyBaseUsdcFinality({
    log, receipt, block: { ...block, hash: "0x" + "11".repeat(32) }, headBlock: 105n, confirmations: 6,
  }), /not canonical/);
});


test("Base RPC scanner bounds ranges and returns only receipt-verified confirmed events", async () => {
  const orderIdHash = "0x" + "ab".repeat(32);
  const buyer = "0x3333333333333333333333333333333333333333";
  const transactionHash = "0x" + "cd".repeat(32);
  const blockHash = "0x" + "ef".repeat(32);
  const topics = encodeEventTopics({
    abi: BASE_USDC_CHECKOUT_ABI,
    eventName: "OrderPaid",
    args: { orderId: orderIdHash, buyer, merchant },
  });
  const data = encodeAbiParameters(
    [{ type: "uint256" }, { type: "address" }],
    [5_000_000n, BASE_USDC_ADDRESS],
  );
  const log = {
    address: contract,
    topics,
    data,
    transactionHash,
    blockHash,
    blockNumber: 100n,
    logIndex: 0,
    removed: false,
  };
  const receipt = { status: "success", transactionHash, blockHash, blockNumber: 100n };
  const block = { hash: blockHash, number: 100n, timestamp: 1_700_000_000n };
  const calls = [];
  const client = {
    async getBlockNumber() { return 120n; },
    async getLogs(args) { calls.push(args); return [log]; },
    async getTransactionReceipt() { return receipt; },
    async getBlock() { return block; },
  };
  const result = await fetchConfirmedBaseUsdcLogs({
    client,
    contractAddress: contract,
    fromBlock: 95n,
    toBlock: 110n,
    confirmations: 6,
  });
  assert.equal(result.headBlock, "120");
  assert.equal(result.scannedToBlock, "110");
  assert.equal(result.events.length, 1);
  assert.equal(result.events[0].orderIdHash, orderIdHash);
  assert.equal(result.events[0].amountMinor, "5000000");
  assert.equal(result.events[0].finality.confirmed, true);
  assert.equal(calls[0].fromBlock, 95n);
  assert.equal(calls[0].toBlock, 110n);
  await assert.rejects(() => fetchConfirmedBaseUsdcLogs({
    client,
    contractAddress: contract,
    fromBlock: 0n,
    toBlock: 1001n,
    confirmations: 6,
  }), /scan limit/);
});

test("Base RPC scanner does not advance when the head has not reached finality", async () => {
  let queried = false;
  const result = await fetchConfirmedBaseUsdcLogs({
    client: {
      async getBlockNumber() { return 4n; },
      async getLogs() { queried = true; return []; },
      async getTransactionReceipt() { throw new Error("not expected"); },
      async getBlock() { throw new Error("not expected"); },
    },
    contractAddress: contract,
    fromBlock: 1n,
    toBlock: 4n,
    confirmations: 6,
  });
  assert.equal(result.scannedToBlock, null);
  assert.equal(result.events.length, 0);
  assert.equal(queried, false);
  assert.throws(() => createBasePublicClient("http://rpc.example"), /HTTPS/);
});


class FakeBaseStatement {
  constructor(db, sql) { this.db = db; this.sql = sql; this.values = []; }
  bind(...values) { this.values = values; return this; }
  async first() {
    if (this.sql.includes("FROM base_usdc_invoices WHERE order_id_hash=?")) {
      return this.db.invoice?.order_id_hash === this.values[0] ? { ...this.db.invoice } : null;
    }
    return null;
  }
  async run() {
    if (this.sql.startsWith("INSERT INTO base_usdc_payment_events")) {
      const [tx, logIndex, orderId, buyer, merchantAddr, token, amount, block, blockHash, observed,
        orderHash, blockTimestamp, invoiceAmount, invoiceMerchant] = this.values;
      const inv = this.db.invoice;
      const allowed = inv?.order_id_hash === orderHash && inv.status === "pending" &&
        !inv.transaction_hash && Number(inv.invoice_deadline) >= blockTimestamp &&
        Number(inv.amount_minor) === invoiceAmount &&
        inv.merchant_address.toLowerCase() === invoiceMerchant.toLowerCase();
      if (!allowed) return { meta: { changes: 0 } };
      this.db.events.push({
        chain_id: 8453, transaction_hash: tx, log_index: logIndex, order_id: orderId,
        buyer_address: buyer, merchant_address: merchantAddr, token_address: token,
        amount_minor: amount, block_number: block, block_hash: blockHash,
        transaction_status: "confirmed", observed_at: observed
      });
      return { meta: { changes: 1 } };
    }
    if (this.sql.startsWith("UPDATE base_usdc_invoices SET status='settled'")) {
      const [buyer, tx, logIndex, block, blockHash, settledAt, expiry, orderHash, eventTx, eventLog] = this.values;
      const inv = this.db.invoice;
      const event = this.db.events.find(row => row.transaction_hash === eventTx && row.log_index === eventLog && row.transaction_status === "confirmed");
      if (inv?.order_id_hash === orderHash && inv.status === "pending" && !inv.transaction_hash && event) {
        Object.assign(inv, {
          status: "settled", buyer_address: buyer, transaction_hash: tx, log_index: logIndex,
          block_number: block, block_hash: blockHash, settled_at: settledAt,
          download_expires_at: expiry
        });
        return { meta: { changes: 1 } };
      }
      return { meta: { changes: 0 } };
    }
    if (this.sql.startsWith("INSERT OR IGNORE INTO base_usdc_agent_revenue_events")) {
      const [cryptoAmount, created, updated, orderHash, tx] = this.values;
      const inv = this.db.invoice;
      if (inv?.order_id_hash === orderHash && inv.status === "settled" && inv.transaction_hash === tx &&
          !this.db.revenue) {
        this.db.revenue = {
          order_id: inv.order_id, agent_id: inv.agent_id, product_id: inv.product_id,
          gross_amount_minor: inv.gross_amount_minor, gross_currency: "usd",
          transaction_hash: inv.transaction_hash, crypto_received_amount: cryptoAmount,
          crypto_currency: "USDC", status: "settled_pending_reconciliation",
          net_amount_minor: null, agent_credit_minor: null, settled_at: inv.settled_at,
          created_at: created, updated_at: updated
        };
        return { meta: { changes: 1 } };
      }
      return { meta: { changes: 0 } };
    }
    if (this.sql.startsWith("INSERT OR IGNORE INTO base_usdc_quarantine")) {
      const [tx, logIndex, reason, eventJson, created] = this.values;
      if (!this.db.quarantine.some(row => row.transaction_hash === tx && row.log_index === logIndex)) {
        this.db.quarantine.push({ transaction_hash: tx, log_index: logIndex, reason, event_json: eventJson, created_at: created });
      }
      return { meta: { changes: 1 } };
    }
    return { meta: { changes: 0 } };
  }
}

function fakeBaseDb() {
  const orderId = "moba-test-order-123";
  const orderIdHash = "0x" + "ab".repeat(32);
  const invoice = {
    order_id: orderId, order_id_hash: orderIdHash,
    product_id: "moba-objective-props", agent_id: "game-asset-builder",
    amount_minor: 5_000_000, gross_amount_minor: 500,
    merchant_address: merchant, invoice_deadline: Math.floor(Date.now() / 1000) + 3600,
    status: "pending", transaction_hash: null,
  };
  const db = {
    invoice, events: [], revenue: null, quarantine: [],
    prepare(sql) { return new FakeBaseStatement(this, sql); },
    async batch(statements) {
      const results = [];
      for (const statement of statements) results.push(await statement.run());
      return results;
    }
  };
  return db;
}

function basePaymentLog() {
  const orderIdHash = "0x" + "ab".repeat(32);
  const buyer = "0x3333333333333333333333333333333333333333";
  return {
    address: contract,
    topics: encodeEventTopics({
      abi: BASE_USDC_CHECKOUT_ABI,
      eventName: "OrderPaid",
      args: { orderId: orderIdHash, buyer, merchant },
    }),
    data: encodeAbiParameters(
      [{ type: "uint256" }, { type: "address" }],
      [5_000_000n, BASE_USDC_ADDRESS],
    ),
    transactionHash: "0x" + "cd".repeat(32),
    blockHash: "0x" + "ef".repeat(32),
    blockNumber: 100n,
    logIndex: 0,
    removed: false,
  };
}

test("Base USDC settlement atomically grants download window and records gross revenue once", async () => {
  const db = fakeBaseDb();
  const log = basePaymentLog();
  const blockTimestamp = Math.floor(Date.now() / 1000);
  const finality = {
    confirmed: true,
    transactionHash: log.transactionHash,
    blockHash: log.blockHash,
    blockNumber: log.blockNumber.toString(),
  };
  const result = await settleBaseUsdcInvoice({
    db, log, finality, blockTimestamp,
    contractAddress: contract, merchantAddress: merchant,
  });
  assert.equal(result.status, "settled");
  assert.equal(db.invoice.status, "settled");
  assert.equal(db.events.length, 1);
  assert.equal(db.revenue.status, "settled_pending_reconciliation");
  assert.equal(db.revenue.gross_amount_minor, 500);
  assert.equal(db.revenue.crypto_received_amount, "5");
  assert.equal(db.revenue.agent_credit_minor, null);
  assert.ok(Date.parse(db.invoice.download_expires_at) > Date.now());

  const duplicate = await settleBaseUsdcInvoice({
    db, log, finality, blockTimestamp,
    contractAddress: contract, merchantAddress: merchant,
  });
  assert.equal(duplicate.status, "duplicate");
  assert.equal(db.events.length, 1);
});

test("Base USDC settlement quarantines mismatches and never unlocks delivery", async () => {
  const db = fakeBaseDb();
  const log = basePaymentLog();
  log.data = encodeAbiParameters(
    [{ type: "uint256" }, { type: "address" }],
    [4_999_999n, BASE_USDC_ADDRESS],
  );
  const result = await settleBaseUsdcInvoice({
    db,
    log,
    finality: {
      confirmed: true, transactionHash: log.transactionHash,
      blockHash: log.blockHash, blockNumber: log.blockNumber.toString(),
    },
    blockTimestamp: Math.floor(Date.now() / 1000),
    contractAddress: contract, merchantAddress: merchant,
  });
  assert.equal(result.status, "quarantined");
  assert.equal(db.invoice.status, "pending");
  assert.equal(db.events.length, 0);
  assert.equal(db.revenue, null);
  assert.equal(db.quarantine.length, 1);
});

test("Base USDC settlement requires finality evidence for the same log", async () => {
  const db = fakeBaseDb();
  const log = basePaymentLog();
  await assert.rejects(() => settleBaseUsdcInvoice({
    db, log,
    finality: { confirmed: true, transactionHash: "0x" + "11".repeat(32), blockHash: log.blockHash, blockNumber: "100" },
    blockTimestamp: Math.floor(Date.now() / 1000),
    contractAddress: contract, merchantAddress: merchant,
  }), /finality evidence/);
});

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
  await assert.rejects(() => recoverBaseUsdcInvoiceSigner({
    orderIdHash: invoice.orderIdHash,
    amountMinor: invoice.amountMinor,
    deadline,
    merchantAddress: merchant,
    contractAddress: contract,
    signature: invoice.signature,
    chainId: BASE_MAINNET_CHAIN_ID,
  }), /recovered|signature|address/i);
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

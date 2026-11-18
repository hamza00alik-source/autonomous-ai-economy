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
  assert.equal(BASE_USDC_ADDRESS.toLowerCase(), "0x833589fc6ed6b6e08f4c7c32d4f71b54bda02913");
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

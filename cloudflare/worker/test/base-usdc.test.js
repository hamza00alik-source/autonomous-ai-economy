import test from "node:test";
import assert from "node:assert/strict";
import { privateKeyToAccount } from "viem/accounts";
import {
  BASE_MAINNET_CHAIN_ID,
  BASE_USDC_ADDRESS,
  signBaseUsdcInvoice,
  recoverBaseUsdcInvoiceSigner,
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

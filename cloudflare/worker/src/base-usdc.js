import {
  createPublicClient,
  decodeEventLog,
  http,
  isAddress,
  keccak256,
  recoverTypedDataAddress,
  stringToHex,
} from "viem";
import { privateKeyToAccount } from "viem/accounts";
import { base } from "viem/chains";

export const BASE_MAINNET_CHAIN_ID = 8453;
export const BASE_USDC_ADDRESS = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913";
export const BASE_INVOICE_DOMAIN = Object.freeze({
  name: "AAE Base USDC Checkout",
  version: "1",
});

export const BASE_INVOICE_TYPES = Object.freeze({
  Invoice: [
    { name: "orderId", type: "bytes32" },
    { name: "amount", type: "uint256" },
    { name: "deadline", type: "uint256" },
    { name: "merchant", type: "address" },
  ],
});

function assertAddress(value, name) {
  if (typeof value !== "string" || !isAddress(value)) {
    throw new Error(name + " must be a valid EVM address");
  }
  return value;
}

function normalizePrivateKey(value) {
  if (typeof value !== "string" || !/^0x[0-9a-f]{64}$/i.test(value)) {
    throw new Error("invoice signer key is missing or malformed");
  }
  return value;
}

/**
 * Signs the exact EIP-712 invoice consumed by BaseUsdcDirectCheckout.sol.
 * The private key must be a dedicated invoice-signing key, never the merchant wallet key.
 * The caller must persist the invoice idempotently before returning the signature to a buyer.
 */
export async function signBaseUsdcInvoice({
  privateKey,
  expectedSignerAddress,
  contractAddress,
  merchantAddress,
  orderId,
  amountMinor,
  deadline,
  chainId = BASE_MAINNET_CHAIN_ID,
}) {
  if (chainId !== BASE_MAINNET_CHAIN_ID) throw new Error("Base mainnet chain ID 8453 is required");
  const contract = assertAddress(contractAddress, "contractAddress");
  const merchant = assertAddress(merchantAddress, "merchantAddress");
  const expectedSigner = assertAddress(expectedSignerAddress, "expectedSignerAddress");
  if (typeof orderId !== "string" || !/^[A-Za-z0-9][A-Za-z0-9._:-]{2,79}$/.test(orderId)) {
    throw new Error("orderId must be a valid server-generated order identifier");
  }
  let amount;
  try { amount = BigInt(amountMinor); } catch { throw new Error("amountMinor must be a positive integer"); }
  if (amount <= 0n || amount > 2n ** 256n - 1n) throw new Error("amountMinor must be a positive uint256");
  if (!Number.isSafeInteger(deadline) || deadline <= Math.floor(Date.now() / 1000)) {
    throw new Error("invoice deadline must be a future Unix timestamp");
  }

  const account = privateKeyToAccount(normalizePrivateKey(privateKey));
  if (account.address.toLowerCase() !== expectedSigner.toLowerCase()) {
    throw new Error("configured invoice signer address does not match the signing key");
  }

  const orderIdHash = keccak256(stringToHex(orderId));
  const domain = {
    ...BASE_INVOICE_DOMAIN,
    chainId: BASE_MAINNET_CHAIN_ID,
    verifyingContract: contract,
  };
  const message = {
    orderId: orderIdHash,
    amount,
    deadline: BigInt(deadline),
    merchant,
  };
  const signature = await account.signTypedData({
    domain,
    types: BASE_INVOICE_TYPES,
    primaryType: "Invoice",
    message,
  });

  return {
    orderId,
    orderIdHash,
    amountMinor: amount.toString(),
    deadline,
    merchantAddress: merchant,
    invoiceSignerAddress: account.address,
    contractAddress: contract,
    chainId: BASE_MAINNET_CHAIN_ID,
    signature,
  };
}

export async function recoverBaseUsdcInvoiceSigner({
  orderIdHash,
  amountMinor,
  deadline,
  merchantAddress,
  contractAddress,
  signature,
  chainId = BASE_MAINNET_CHAIN_ID,
}) {
  if (chainId !== BASE_MAINNET_CHAIN_ID) throw new Error("Base mainnet chain ID 8453 is required");
  if (typeof orderIdHash !== "string" || !/^0x[0-9a-f]{64}$/i.test(orderIdHash)) {
    throw new Error("orderIdHash must be bytes32");
  }
  const amount = BigInt(amountMinor);
  const merchant = assertAddress(merchantAddress, "merchantAddress");
  const contract = assertAddress(contractAddress, "contractAddress");
  return recoverTypedDataAddress({
    domain: {
      ...BASE_INVOICE_DOMAIN,
      chainId: BASE_MAINNET_CHAIN_ID,
      verifyingContract: contract,
    },
    types: BASE_INVOICE_TYPES,
    primaryType: "Invoice",
    message: { orderId: orderIdHash, amount, deadline: BigInt(deadline), merchant },
    signature,
  });
}


export const BASE_USDC_CHECKOUT_ABI = [{
  type: "event",
  name: "OrderPaid",
  anonymous: false,
  inputs: [
    { indexed: true, name: "orderId", type: "bytes32" },
    { indexed: true, name: "buyer", type: "address" },
    { indexed: true, name: "merchant", type: "address" },
    { indexed: false, name: "amount", type: "uint256" },
    { indexed: false, name: "token", type: "address" },
  ],
}];

/**
 * Strictly decodes and validates the checkout contract event against the
 * server-side invoice and deployment configuration. This is not, by itself,
 * proof of finality: the indexer must separately verify receipt, canonical
 * block hash and the configured confirmation threshold.
 */
export function decodeBaseUsdcPaymentLog(log, expected) {
  const contract = assertAddress(expected?.contractAddress, "expected.contractAddress");
  const merchant = assertAddress(expected?.merchantAddress, "expected.merchantAddress");
  const token = assertAddress(expected?.tokenAddress || BASE_USDC_ADDRESS, "expected.tokenAddress");
  if (expected?.chainId !== BASE_MAINNET_CHAIN_ID) throw new Error("unexpected Base chain ID");
  if (!log || typeof log !== "object" || log.removed === true) throw new Error("removed or malformed chain log");
  if (typeof log.address !== "string" || log.address.toLowerCase() !== contract.toLowerCase()) {
    throw new Error("event emitter does not match the configured checkout contract");
  }
  if (typeof log.transactionHash !== "string" || !/^0x[0-9a-f]{64}$/i.test(log.transactionHash) ||
      typeof log.blockHash !== "string" || !/^0x[0-9a-f]{64}$/i.test(log.blockHash) ||
      typeof log.blockNumber !== "bigint" || log.blockNumber < 0n ||
      !Number.isSafeInteger(log.logIndex) || log.logIndex < 0) {
    throw new Error("chain log is missing canonical transaction or block coordinates");
  }
  const decoded = decodeEventLog({
    abi: BASE_USDC_CHECKOUT_ABI,
    data: log.data,
    topics: log.topics,
    strict: true,
  });
  if (decoded.eventName !== "OrderPaid") throw new Error("unexpected contract event");
  const args = decoded.args;
  if (typeof expected.orderIdHash !== "string" ||
      args.orderId.toLowerCase() !== expected.orderIdHash.toLowerCase()) {
    throw new Error("payment order ID does not match the invoice");
  }
  if (args.merchant.toLowerCase() !== merchant.toLowerCase()) {
    throw new Error("payment merchant does not match the invoice");
  }
  if (args.token.toLowerCase() !== token.toLowerCase()) {
    throw new Error("payment token is not native Base USDC");
  }
  let expectedAmount;
  try { expectedAmount = BigInt(expected.amountMinor); } catch {
    throw new Error("expected invoice amount is invalid");
  }
  if (expectedAmount <= 0n || args.amount !== expectedAmount) {
    throw new Error("payment amount does not exactly match the invoice");
  }
  return {
    chainId: BASE_MAINNET_CHAIN_ID,
    orderIdHash: args.orderId,
    buyerAddress: args.buyer,
    merchantAddress: args.merchant,
    tokenAddress: args.token,
    amountMinor: args.amount.toString(),
    transactionHash: log.transactionHash,
    logIndex: log.logIndex,
    blockNumber: log.blockNumber.toString(),
    blockHash: log.blockHash,
  };
}


/**
 * Verifies an RPC-retrieved receipt and block against a decoded log and
 * enforces the configured confirmation depth. The caller must fetch these
 * values from its trusted Base RPC endpoint and persist only after this passes.
 */
export function verifyBaseUsdcFinality({ log, receipt, block, headBlock, confirmations }) {
  if (!Number.isSafeInteger(confirmations) || confirmations < 1 || confirmations > 10000) {
    throw new Error("confirmation threshold must be between 1 and 10000");
  }
  if (!log || !receipt || !block || typeof headBlock !== "bigint") {
    throw new Error("receipt, block and head block evidence are required");
  }
  if (receipt.status !== "success") throw new Error("payment transaction did not succeed");
  if (receipt.transactionHash?.toLowerCase() !== log.transactionHash?.toLowerCase()) {
    throw new Error("receipt transaction hash does not match the event");
  }
  if (receipt.blockHash?.toLowerCase() !== log.blockHash?.toLowerCase() ||
      block.hash?.toLowerCase() !== log.blockHash?.toLowerCase()) {
    throw new Error("event block is not canonical according to the RPC response");
  }
  if (receipt.blockNumber !== log.blockNumber || block.number !== log.blockNumber) {
    throw new Error("receipt and event block numbers do not match");
  }
  const requiredHead = log.blockNumber + BigInt(confirmations) - 1n;
  if (headBlock < requiredHead) throw new Error("payment has not reached the required confirmation depth");
  return {
    confirmed: true,
    confirmations: Number(headBlock - log.blockNumber + 1n),
    blockNumber: log.blockNumber.toString(),
    blockHash: log.blockHash,
    transactionHash: log.transactionHash,
  };
}


export function createBasePublicClient(rpcUrl) {
  let parsed;
  try { parsed = new URL(rpcUrl); } catch { throw new Error("BASE_RPC_URL must be a valid HTTPS URL"); }
  if (parsed.protocol !== "https:" || !parsed.hostname) {
    throw new Error("BASE_RPC_URL must use HTTPS");
  }
  return createPublicClient({
    chain: base,
    transport: http(parsed.toString(), { timeout: 10_000, retryCount: 1 }),
  });
}

/**
 * Retrieves only confirmed OrderPaid logs from a bounded block range.
 * It never writes to D1 or grants downloads; the caller must match each event
 * to a pending invoice and commit settlement atomically.
 */
export async function fetchConfirmedBaseUsdcLogs({
  client,
  contractAddress,
  fromBlock,
  toBlock,
  confirmations,
  maxRange = 1000,
}) {
  const contract = assertAddress(contractAddress, "contractAddress");
  if (!client || typeof client.getBlockNumber !== "function" ||
      typeof client.getLogs !== "function" ||
      typeof client.getTransactionReceipt !== "function" ||
      typeof client.getBlock !== "function") {
    throw new Error("a complete Base public client is required");
  }
  if (!Number.isSafeInteger(confirmations) || confirmations < 1 || confirmations > 10000) {
    throw new Error("confirmation threshold must be between 1 and 10000");
  }
  const start = BigInt(fromBlock);
  const requestedEnd = BigInt(toBlock);
  if (start < 0n || requestedEnd < start) throw new Error("invalid block range");
  if (requestedEnd - start + 1n > BigInt(maxRange)) throw new Error("block range exceeds configured scan limit");
  const headBlock = await client.getBlockNumber();
  const finalizableEnd = headBlock - BigInt(confirmations) + 1n;
  const end = requestedEnd < finalizableEnd ? requestedEnd : finalizableEnd;
  if (end < start) return { headBlock: headBlock.toString(), scannedToBlock: null, events: [] };

  const logs = await client.getLogs({
    address: contract,
    event: BASE_USDC_CHECKOUT_ABI[0],
    fromBlock: start,
    toBlock: end,
  });
  const events = [];
  for (const log of logs) {
    const decoded = decodeEventLog({
      abi: BASE_USDC_CHECKOUT_ABI,
      data: log.data,
      topics: log.topics,
      strict: true,
    });
    if (decoded.eventName !== "OrderPaid") throw new Error("unexpected event returned by Base RPC");
    const [receipt, block] = await Promise.all([
      client.getTransactionReceipt({ hash: log.transactionHash }),
      client.getBlock({ blockNumber: log.blockNumber }),
    ]);
    const finality = verifyBaseUsdcFinality({
      log, receipt, block, headBlock, confirmations,
    });
    events.push({
      orderIdHash: decoded.args.orderId,
      buyerAddress: decoded.args.buyer,
      merchantAddress: decoded.args.merchant,
      amountMinor: decoded.args.amount.toString(),
      tokenAddress: decoded.args.token,
      transactionHash: log.transactionHash,
      logIndex: log.logIndex,
      blockNumber: log.blockNumber.toString(),
      blockHash: log.blockHash,
      finality,
    });
  }
  return {
    headBlock: headBlock.toString(),
    scannedToBlock: end.toString(),
    events,
  };
}

import {
  createPublicClient,
  decodeEventLog,
  formatUnits,
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
    if (typeof block.timestamp !== "bigint" || block.timestamp <= 0n ||
        block.timestamp > BigInt(Number.MAX_SAFE_INTEGER)) {
      throw new Error("canonical block timestamp is missing or unsafe");
    }
    events.push({
      blockTimestamp: Number(block.timestamp),
      rawLog: log,
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


async function quarantineBaseUsdcEvent(db, log, reason, now) {
  await db.prepare(
    "INSERT OR IGNORE INTO base_usdc_quarantine (transaction_hash,log_index,reason,event_json,created_at) VALUES (?,?,?,?,?)"
  ).bind(
    String(log?.transactionHash || "unknown"),
    Number.isSafeInteger(log?.logIndex) ? log.logIndex : -1,
    String(reason).slice(0, 240),
    JSON.stringify({
      address: log?.address || null,
      topics: log?.topics || null,
      data: log?.data || null,
      transactionHash: log?.transactionHash || null,
      blockHash: log?.blockHash || null,
      blockNumber: log?.blockNumber?.toString?.() || null,
      logIndex: log?.logIndex ?? null,
    }),
    now,
  ).run();
}

/**
 * Matches one finalized contract event to a pending invoice, then commits the
 * payment event, invoice entitlement and gross revenue attribution in one D1
 * batch. No payout or agent credit is created here.
 */
export async function settleBaseUsdcInvoice({
  db,
  log,
  finality,
  blockTimestamp,
  contractAddress,
  merchantAddress,
  tokenAddress = BASE_USDC_ADDRESS,
}) {
  if (!db || typeof db.prepare !== "function" || typeof db.batch !== "function") {
    throw new Error("D1 database with batch transaction support is required");
  }
  if (!finality?.confirmed || finality.transactionHash?.toLowerCase() !== log?.transactionHash?.toLowerCase() ||
      finality.blockHash?.toLowerCase() !== log?.blockHash?.toLowerCase() ||
      finality.blockNumber !== log?.blockNumber?.toString?.()) {
    throw new Error("verified finality evidence is required for this exact log");
  }
  if (!Number.isSafeInteger(blockTimestamp) || blockTimestamp <= 0) {
    throw new Error("canonical block timestamp is required");
  }
  const now = new Date().toISOString();
  const decoded = decodeEventLog({
    abi: BASE_USDC_CHECKOUT_ABI,
    data: log.data,
    topics: log.topics,
    strict: true,
  });
  const orderIdHash = decoded.args.orderId;
  const invoice = await db.prepare(
    "SELECT order_id,order_id_hash,product_id,agent_id,amount_minor,gross_amount_minor,merchant_address,invoice_deadline,status,transaction_hash FROM base_usdc_invoices WHERE order_id_hash=?"
  ).bind(orderIdHash).first();

  if (!invoice) {
    await quarantineBaseUsdcEvent(db, log, "unknown_order", now);
    return { status: "quarantined", reason: "unknown_order" };
  }
  let verified;
  try {
    verified = decodeBaseUsdcPaymentLog(log, {
      chainId: BASE_MAINNET_CHAIN_ID,
      contractAddress,
      merchantAddress: invoice.merchant_address,
      tokenAddress,
      orderIdHash: invoice.order_id_hash,
      amountMinor: String(invoice.amount_minor),
    });
    if (invoice.merchant_address.toLowerCase() !== merchantAddress.toLowerCase()) {
      throw new Error("invoice merchant differs from configured merchant");
    }
    if (blockTimestamp > Number(invoice.invoice_deadline)) {
      throw new Error("payment event occurred after invoice expiry");
    }
  } catch (error) {
    const reason = String(error?.message || "invoice_mismatch").slice(0, 240);
    await quarantineBaseUsdcEvent(db, log, reason, now);
    return { status: "quarantined", reason };
  }

  if (invoice.status === "settled" && invoice.transaction_hash?.toLowerCase() === verified.transactionHash.toLowerCase()) {
    return { status: "duplicate", order_id: invoice.order_id };
  }
  if (invoice.status !== "pending" || invoice.transaction_hash) {
    await quarantineBaseUsdcEvent(db, log, "invoice_not_pending_or_already_paid", now);
    return { status: "quarantined", reason: "invoice_not_pending_or_already_paid" };
  }

  const settledAt = new Date(blockTimestamp * 1000).toISOString();
  const downloadExpiresAt = new Date((blockTimestamp + 7 * 24 * 60 * 60) * 1000).toISOString();
  const cryptoAmount = formatUnits(BigInt(invoice.amount_minor), 6);
  const statements = [
    db.prepare(
      "INSERT INTO base_usdc_payment_events (chain_id,transaction_hash,log_index,order_id,buyer_address,merchant_address,token_address,amount_minor,block_number,block_hash,transaction_status,observed_at) SELECT 8453,?,?,?,?,?,?,?,?,?,'confirmed',? WHERE EXISTS (SELECT 1 FROM base_usdc_invoices WHERE order_id_hash=? AND status='pending' AND transaction_hash IS NULL AND invoice_deadline>=? AND amount_minor=? AND merchant_address=?)"
    ).bind(
      verified.transactionHash, verified.logIndex, invoice.order_id, verified.buyerAddress,
      verified.merchantAddress, verified.tokenAddress, Number(verified.amountMinor),
      Number(verified.blockNumber), verified.blockHash, now, invoice.order_id_hash,
      blockTimestamp, Number(invoice.amount_minor), invoice.merchant_address,
    ),
    db.prepare(
      "UPDATE base_usdc_invoices SET status='settled',buyer_address=?,transaction_hash=?,log_index=?,block_number=?,block_hash=?,settled_at=?,download_expires_at=?,updated_at=? WHERE order_id_hash=? AND status='pending' AND transaction_hash IS NULL AND EXISTS (SELECT 1 FROM base_usdc_payment_events WHERE chain_id=8453 AND transaction_hash=? AND log_index=? AND transaction_status='confirmed')"
    ).bind(
      verified.buyerAddress, verified.transactionHash, verified.logIndex,
      Number(verified.blockNumber), verified.blockHash, settledAt, downloadExpiresAt, now,
      invoice.order_id_hash, verified.transactionHash, verified.logIndex,
    ),
    db.prepare(
      "INSERT OR IGNORE INTO base_usdc_agent_revenue_events (order_id,agent_id,product_id,gross_amount_minor,gross_currency,transaction_hash,crypto_received_amount,crypto_currency,status,net_amount_minor,agent_credit_minor,settled_at,reconciled_at,created_at,updated_at) SELECT order_id,agent_id,product_id,gross_amount_minor,'usd',transaction_hash,?,'USDC','settled_pending_reconciliation',NULL,NULL,settled_at,NULL,?,? FROM base_usdc_invoices WHERE order_id_hash=? AND status='settled' AND transaction_hash=?"
    ).bind(cryptoAmount, now, now, invoice.order_id_hash, verified.transactionHash),
  ];
  await db.batch(statements);
  const saved = await db.prepare(
    "SELECT status,transaction_hash,download_expires_at FROM base_usdc_invoices WHERE order_id_hash=?"
  ).bind(invoice.order_id_hash).first();
  if (saved?.status !== "settled" || saved.transaction_hash?.toLowerCase() !== verified.transactionHash.toLowerCase()) {
    return { status: "conflict", order_id: invoice.order_id };
  }
  return {
    status: "settled",
    order_id: invoice.order_id,
    transaction_hash: verified.transactionHash,
    download_expires_at: saved.download_expires_at,
    gross_amount_minor: invoice.gross_amount_minor,
    gross_currency: "USD",
    agent_credit_minor: null,
  };
}


/**
 * Scheduled D1-backed Base indexer. Disabled unless explicitly configured.
 * It rewinds a recent window on a detected cursor reorg and revokes affected
 * entitlements for manual review instead of silently trusting an orphaned log.
 */
export async function pollBaseUsdc(env, injectedClient = null) {
  if (env.AAE_BASE_USDC_INDEXER_ENABLED !== "true") return { enabled: false };
  if (!env.DB || typeof env.DB.prepare !== "function" || typeof env.DB.batch !== "function") {
    throw new Error("D1 database is required for the Base indexer");
  }
  const contractAddress = assertAddress(env.BASE_CHECKOUT_CONTRACT_ADDRESS, "BASE_CHECKOUT_CONTRACT_ADDRESS");
  const merchantAddress = assertAddress(env.BASE_MERCHANT_ADDRESS, "BASE_MERCHANT_ADDRESS");
  const deploymentBlock = Number(env.BASE_DEPLOYMENT_BLOCK);
  const confirmations = Number(env.BASE_CONFIRMATIONS);
  const maxBlocks = Number(env.BASE_MAX_BLOCKS_PER_POLL || 500);
  if (!Number.isSafeInteger(deploymentBlock) || deploymentBlock < 0 ||
      !Number.isSafeInteger(confirmations) || confirmations < 1 || confirmations > 10000 ||
      !Number.isSafeInteger(maxBlocks) || maxBlocks < 1 || maxBlocks > 1000) {
    throw new Error("Base indexer block and confirmation settings are invalid");
  }
  const client = injectedClient || createBasePublicClient(env.BASE_RPC_URL);
  const now = new Date().toISOString();
  await env.DB.prepare(
    "INSERT OR IGNORE INTO base_usdc_indexer_state (id,next_block,last_block_hash,updated_at) VALUES (1,?,NULL,?)"
  ).bind(deploymentBlock, now).run();
  const cursor = await env.DB.prepare(
    "SELECT next_block,last_block_hash,halted_at,halt_reason FROM base_usdc_indexer_state WHERE id=1"
  ).first();
  if (!cursor || !Number.isSafeInteger(Number(cursor.next_block))) {
    throw new Error("Base indexer cursor is missing or invalid");
  }
  if (cursor.halted_at) {
    return {
      enabled: true,
      halted: true,
      halted_at: cursor.halted_at,
      halt_reason: cursor.halt_reason || "manual_review_required",
      manual_review_required: true,
      scanned: 0,
    };
  }
  const nextBlock = Number(cursor.next_block);

  if (nextBlock > deploymentBlock && cursor.last_block_hash) {
    const priorNumber = BigInt(nextBlock - 1);
    const canonicalPrior = await client.getBlock({ blockNumber: priorNumber });
    if (canonicalPrior.hash?.toLowerCase() !== String(cursor.last_block_hash).toLowerCase()) {
      // A cursor mismatch does not reveal how deep the reorg is. Never guess a
      // safe rewind depth: freeze all settlement-derived access and require
      // operator reconciliation before any further automatic indexing.
      const incidentAt = new Date().toISOString();
      const reason = "checkpoint_hash_mismatch";
      await env.DB.batch([
        env.DB.prepare(
          "UPDATE base_usdc_invoices SET status='review',download_expires_at=?,updated_at=? WHERE status='settled'"
        ).bind(incidentAt, incidentAt),
        env.DB.prepare(
          "UPDATE base_usdc_agent_revenue_events SET status='refund_review',updated_at=? WHERE status IN ('settled_pending_reconciliation','reconciled')"
        ).bind(incidentAt, incidentAt),
        env.DB.prepare(
          "UPDATE base_usdc_indexer_state SET halted_at=?,halt_reason=?,updated_at=? WHERE id=1 AND halted_at IS NULL"
        ).bind(incidentAt, reason, incidentAt),
      ]);
      console.error("AAE Base indexer halted: checkpoint hash mismatch; all prior settlements require manual reconciliation.");
      return {
        enabled: true,
        halted: true,
        reorg_detected: true,
        manual_review_required: true,
        halted_at: incidentAt,
        halt_reason: reason,
        automatic_scanning_stopped: true,
      };
    }
  }

  const fromBlock = BigInt(nextBlock);
  const toBlock = fromBlock + BigInt(maxBlocks) - 1n;
  const scan = await fetchConfirmedBaseUsdcLogs({
    client, contractAddress, fromBlock, toBlock, confirmations,
    maxRange: maxBlocks,
  });
  if (scan.scannedToBlock === null) {
    return { enabled: true, scanned: 0, settled: 0, quarantined: 0, waiting_for_confirmations: true };
  }

  let settled = 0;
  let quarantined = 0;
  for (const event of scan.events) {
    const result = await settleBaseUsdcInvoice({
      db: env.DB,
      log: event.rawLog,
      finality: event.finality,
      blockTimestamp: event.blockTimestamp,
      contractAddress,
      merchantAddress,
    });
    if (result.status === "settled") settled += 1;
    if (result.status === "quarantined") quarantined += 1;
    if (result.status === "conflict") throw new Error("Base invoice settlement conflict; cursor was not advanced");
  }

  const checkpointNumber = BigInt(scan.scannedToBlock);
  const checkpoint = await client.getBlock({ blockNumber: checkpointNumber });
  if (typeof checkpoint.hash !== "string" || !/^0x[0-9a-f]{64}$/i.test(checkpoint.hash)) {
    throw new Error("Base indexer checkpoint block hash is invalid");
  }
  await env.DB.prepare(
    "UPDATE base_usdc_indexer_state SET next_block=?,last_block_hash=?,updated_at=? WHERE id=1"
  ).bind(Number(checkpointNumber + 1n), checkpoint.hash, new Date().toISOString()).run();

  return {
    enabled: true,
    scanned_from_block: nextBlock,
    scanned_to_block: scan.scannedToBlock,
    events_seen: scan.events.length,
    settled,
    quarantined,
    head_block: scan.headBlock,
  };
}

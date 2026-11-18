import {
  isAddress,
  keccak256,
  recoverTypedDataAddress,
  stringToHex,
} from "viem";
import { privateKeyToAccount } from "viem/accounts";

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

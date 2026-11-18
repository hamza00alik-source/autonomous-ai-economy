import {
  createPublicClient,
  createWalletClient,
  custom,
  formatUnits,
  getAddress,
  http,
} from "viem";
import { base } from "viem/chains";

const CHAIN_ID = 8453;
const USDC = getAddress("0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913");
const STORE_KEY = "aae-base-usdc-order:";
const checkoutAbi = [{
  type: "function",
  name: "pay",
  stateMutability: "nonpayable",
  inputs: [
    { name: "orderId", type: "bytes32" },
    { name: "amount", type: "uint256" },
    { name: "deadline", type: "uint256" },
    { name: "signature", type: "bytes" },
  ],
  outputs: [],
}];
const usdcAbi = [
  { type: "function", name: "approve", stateMutability: "nonpayable",
    inputs: [{ name: "spender", type: "address" }, { name: "value", type: "uint256" }],
    outputs: [{ name: "", type: "bool" }] },
  { type: "function", name: "balanceOf", stateMutability: "view",
    inputs: [{ name: "account", type: "address" }], outputs: [{ name: "", type: "uint256" }] },
];

const buy = document.getElementById("buy");
const download = document.getElementById("download");
const message = document.getElementById("message");
const query = new URLSearchParams(location.search);
const publicClient = createPublicClient({ chain: base, transport: http() });
let activeOrder = query.get("order");
let accessToken = activeOrder ? localStorage.getItem(STORE_KEY + activeOrder + ":token") : null;
let invoice = activeOrder ? readInvoice(activeOrder) : null;
let polling = false;

function readInvoice(id) {
  try { return JSON.parse(localStorage.getItem(STORE_KEY + id + ":invoice") || "null"); }
  catch { return null; }
}
function show(text) { message.textContent = text; }
function showDownload(visible) { download.hidden = !visible; download.style.display = visible ? "block" : "none"; }
function saveOrder(data) {
  activeOrder = data.order_id;
  accessToken = data.access_token;
  invoice = data;
  localStorage.setItem(STORE_KEY + activeOrder + ":token", accessToken);
  localStorage.setItem(STORE_KEY + activeOrder + ":invoice", JSON.stringify(data));
  history.replaceState(null, "", "?order=" + encodeURIComponent(activeOrder));
}
function friendlyError(error) {
  if (error?.code === 4001 || error?.cause?.code === 4001) return "Wallet request rejected. No further transaction was submitted.";
  return error?.shortMessage || error?.message || "The checkout could not continue.";
}
async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { ...(options.headers || {}), Authorization: "Bearer " + accessToken },
    cache: "no-store",
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || "Store request failed (" + response.status + ")");
  return data;
}
async function refreshOrder() {
  if (!activeOrder || !accessToken) return;
  const data = await api("/v1/store/base-usdc/orders/" + encodeURIComponent(activeOrder));
  if (data.download_available) {
    show("Payment confirmed by the Base indexer. Your download is ready.");
    showDownload(true);
    polling = false;
    return true;
  }
  show("On-chain payment submitted. Server status: " + data.status +
    ". The download stays locked until independent confirmation.");
  return false;
}
async function pollUntilSettled() {
  if (polling) return;
  polling = true;
  for (let attempt = 0; attempt < 360; attempt++) {
    try {
      if (await refreshOrder()) return;
    } catch (error) { show("Checking payment status… " + friendlyError(error)); }
    await new Promise(resolve => setTimeout(resolve, 5000));
  }
  show("Payment is still not confirmed. Keep this order link and check again later; do not pay a second time.");
  polling = false;
}
async function connectAndPay(data) {
  if (!window.ethereum?.request) throw new Error("No compatible browser wallet was detected. Open this page in a Base-compatible wallet browser.");
  const wallet = createWalletClient({ chain: base, transport: custom(window.ethereum) });
  await wallet.requestAddresses();
  const [account] = await wallet.getAddresses();
  if (!account) throw new Error("The wallet did not provide an account.");
  const chainHex = await window.ethereum.request({ method: "eth_chainId" });
  if (Number.parseInt(chainHex, 16) !== CHAIN_ID) {
    show("Switching your wallet to Base…");
    await wallet.switchChain({ id: CHAIN_ID });
  }

  const contract = getAddress(data.contract_address);
  const merchant = getAddress(data.merchant_address);
  const token = getAddress(data.token_address);
  if (token !== USDC || data.chain_id !== CHAIN_ID) throw new Error("Invoice token or network does not match native Base USDC.");
  if (!/^0x[0-9a-fA-F]{64}$/.test(data.order_id_hash) ||
      !/^0x[0-9a-fA-F]{130}$/.test(data.signature)) throw new Error("The signed invoice is malformed.");
  if (Number(data.deadline) <= Math.floor(Date.now() / 1000)) throw new Error("This invoice has expired. Start a new checkout.");
  const code = await publicClient.getBytecode({ address: contract });
  if (!code || code === "0x") throw new Error("The checkout contract is not deployed at the configured address. No USDC approval was requested.");
  const amount = BigInt(data.amount_minor);
  const balance = await publicClient.readContract({ address: token, abi: usdcAbi, functionName: "balanceOf", args: [account] });
  if (balance < amount) throw new Error("Insufficient Base USDC. Wallet balance: " + formatUnits(balance, 6) + " USDC; required: " + formatUnits(amount, 6) + " USDC.");

  show("Approve exactly " + formatUnits(amount, 6) + " USDC for this checkout contract. No unlimited allowance is requested.");
  const approvalHash = await wallet.writeContract({
    account, address: token, abi: usdcAbi, functionName: "approve", args: [contract, amount],
  });
  show("USDC approval submitted (" + approvalHash + "). Waiting for confirmation before payment…");
  const approvalReceipt = await publicClient.waitForTransactionReceipt({ hash: approvalHash });
  if (approvalReceipt.status !== "success") throw new Error("USDC approval transaction failed. No payment was submitted.");

  show("Approval confirmed. Review and confirm the exact 5 USDC payment in your wallet…");
  const paymentHash = await wallet.writeContract({
    account, address: contract, abi: checkoutAbi, functionName: "pay",
    args: [data.order_id_hash, amount, BigInt(data.deadline), data.signature],
  });
  show("Payment transaction submitted: " + paymentHash + ". Waiting for independent server confirmation…");
  await pollUntilSettled();
}
buy.addEventListener("click", async () => {
  buy.disabled = true;
  showDownload(false);
  try {
    if (!invoice || !activeOrder || !accessToken) {
      show("Creating a fixed-price $5 Base USDC invoice…");
      const response = await fetch("/v1/store/base-usdc/checkout", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: "{}",
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.error || "Base USDC checkout is unavailable.");
      saveOrder(data);
    }
    await connectAndPay(invoice);
  } catch (error) {
    show(friendlyError(error));
    buy.disabled = false;
  }
});
download.addEventListener("click", async () => {
  if (!activeOrder || !accessToken) return;
  download.disabled = true;
  try {
    const response = await fetch("/v1/store/base-usdc/orders/" + encodeURIComponent(activeOrder) + "/download", {
      headers: { Authorization: "Bearer " + accessToken }, cache: "no-store",
    });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(data.error || "Download is not available.");
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url; link.download = "moba-objective-props.zip";
    document.body.appendChild(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 30_000);
    show("Download started. Keep this browser's private order access until the seven-day download window ends.");
  } catch (error) { show(friendlyError(error)); }
  finally { download.disabled = false; }
});

if (activeOrder && accessToken && invoice) {
  refreshOrder().then(available => { if (!available) pollUntilSettled(); }).catch(error => show(friendlyError(error)));
} else if (activeOrder) {
  show("This order's private browser access is missing. Reopen the original browser used to start checkout.");
} else {
  show("Checkout is staged and gated. Choose Buy only when the store owner has enabled live checkout.");
}

import test from "node:test";
import assert from "node:assert/strict";
import { parseUsdcAmount, buildBaseUsdcPaymentUri, canonicalReceivingWalletPayload } from "../src/receiving_wallets.js";

test("USDC amount parser uses exact six-decimal integer units",()=>{
  assert.equal(parseUsdcAmount("1"),1_000_000);
  assert.equal(parseUsdcAmount("0.000001"),1);
  assert.equal(parseUsdcAmount("12.34"),12_340_000);
  assert.equal(parseUsdcAmount("0"),null);
  assert.equal(parseUsdcAmount("0.0000001"),null);
  assert.equal(parseUsdcAmount("01.00"),null);
  assert.equal(parseUsdcAmount("1e2"),null);
  assert.equal(parseUsdcAmount(1),null);
});

test("payment URI binds the Base USDC contract, chain and exact amount",()=>{
  const address="0x1111111111111111111111111111111111111111";
  assert.equal(buildBaseUsdcPaymentUri(address,1_500_000),
    "ethereum:0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913@8453/transfer?address="+address+"&uint256=1500000");
  assert.equal(buildBaseUsdcPaymentUri("not-an-address",1),null);
  assert.equal(buildBaseUsdcPaymentUri(address,0),null);
});

test("owner signing payload canonicalization is stable across object key order",()=>{
  assert.equal(canonicalReceivingWalletPayload({b:2,a:1}),canonicalReceivingWalletPayload({a:1,b:2}));
});

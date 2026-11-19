"""Read-only, multi-RPC reconciliation of the shared USDC treasury."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .collective_treasury import CollectiveTreasuryStore
from .evm_rpc import EVMJSONRPCSource, EVMRPCConfig


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare AAE's pooled ledger with the shared wallet's on-chain USDC balance."
    )
    parser.add_argument("--rpc-urls", default=os.getenv("AAE_EVM_RPC_URLS", ""))
    parser.add_argument("--network", choices=("base-sepolia", "base"), default="base-sepolia")
    parser.add_argument("--chain-id", type=int, default=None)
    parser.add_argument("--asset", default="USDC")
    parser.add_argument("--token-contract", required=True)
    parser.add_argument("--minimum-native-balance-wei", type=int, default=0,
                        help="Optional minimum native ETH balance required for gas.")
    parser.add_argument("--data-dir", type=Path, default=Path("./data"))
    args = parser.parse_args()
    if args.minimum_native_balance_wei < 0:
        parser.error("--minimum-native-balance-wei must be non-negative")
    chain_id = args.chain_id or {"base-sepolia": 84532, "base": 8453}[args.network]

    urls = tuple(dict.fromkeys(part.strip() for part in args.rpc_urls.split(",") if part.strip()))
    if len(urls) < 2:
        parser.error("provide at least two independent RPC URLs via --rpc-urls or AAE_EVM_RPC_URLS")

    store = CollectiveTreasuryStore(args.data_dir / "collective_treasury.sqlite3")
    wallet = store.treasury_wallet(args.network, args.asset)
    if not wallet:
        parser.error("no collective treasury wallet is registered for this network and asset")

    balances = []
    native_balances = []
    for url in urls:
        source = EVMJSONRPCSource(EVMRPCConfig(
            rpc_url=url, network=args.network, chain_id=chain_id,
            asset=args.asset, token_contract=args.token_contract,
            start_block=0,
        ))
        balances.append(source.token_balance(wallet.address))
        native_balances.append(source.native_balance(wallet.address))

    if len(set(balances)) != 1:
        raise RuntimeError("independent RPC providers disagree on treasury token balance; reconciliation failed closed")

    if len(set(native_balances)) != 1:
        raise RuntimeError("independent RPC providers disagree on native gas balance; reconciliation failed closed")

    result = store.reconcile_onchain_balance(args.network, args.asset, balances[0])
    result["providers_agreed"] = len(balances)
    result["wallet_address"] = wallet.address
    result["native_balance_wei"] = native_balances[0]
    result["minimum_native_balance_wei"] = args.minimum_native_balance_wei
    result["gas_reserve_ok"] = native_balances[0] >= args.minimum_native_balance_wei
    print(json.dumps(result, indent=2))
    if not result["fully_reconciled"] or not result["gas_reserve_ok"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()

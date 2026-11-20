"""Provision the single AAE collective treasury wallet through Coinbase CDP."""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from .collective_treasury import CDPServerTreasuryWallet, CollectiveTreasuryStore


async def _provision(args: argparse.Namespace) -> dict:
    adapter = CDPServerTreasuryWallet(account_name=args.account_name)
    wallet = await adapter.ensure_wallet(network=args.network)
    store = CollectiveTreasuryStore(Path(args.data_dir) / "collective_treasury.sqlite3")
    store.register_treasury_wallet(wallet)
    return {
        "status": "ready",
        "provider": wallet.provider,
        "provider_wallet_id": wallet.provider_wallet_id,
        "network": wallet.network,
        "asset": wallet.asset,
        "address": wallet.address,
        "funds_moved": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Provision or recover AAE's one shared CDP treasury wallet."
    )
    parser.add_argument(
        "--network", choices=("base-sepolia", "base"), default="base-sepolia",
        help="Base Sepolia testnet by default; Base mainnet requires --confirm-mainnet.",
    )
    parser.add_argument("--confirm-mainnet", action="store_true")
    parser.add_argument("--account-name", default="AAE_MASTER_TREASURY")
    parser.add_argument("--data-dir", type=Path, default=Path("./data"))
    args = parser.parse_args()
    if args.network == "base" and not args.confirm_mainnet:
        parser.error("Base mainnet requires explicit --confirm-mainnet")
    result = asyncio.run(_provision(args))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

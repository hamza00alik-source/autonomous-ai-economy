"""Local owner console for simulated agent financial controls.

This CLI is intended for trusted local administration only. It is not an
authenticated network API or a public dashboard. It never sends payments.
"""
from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path

from .expense_scheduler import AgentExpenseScheduler
from .financial_ledger import DoubleEntryLedger
from .financial_policy import FinancialPolicyStore, _canonical
from .financial_spending import AgentSpending
from .identity import ParticipantRegistry


def _services(data_dir: Path):
    data_dir.mkdir(parents=True, exist_ok=True)
    registry = ParticipantRegistry(data_dir / "participants.sqlite3")
    policies = FinancialPolicyStore(registry, data_dir / "financial-policies.sqlite3")
    ledger = DoubleEntryLedger(data_dir / "financial-ledger.sqlite3")
    spending = AgentSpending(ledger, policies, data_dir / "financial-spending.sqlite3")
    scheduler = AgentExpenseScheduler(spending, data_dir / "financial-expense-schedules.sqlite3")
    return registry, policies, ledger, spending, scheduler


def _print_json(value) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser(description="Local owner controls for simulated AAE finances")
    parser.add_argument("--data-dir", type=Path, default=Path("./data"))
    sub = parser.add_subparsers(dest="command", required=True)

    policies_cmd = sub.add_parser("policies", help="list policies and their current authorization state")
    policies_cmd.add_argument("--agent-id")
    budget_cmd = sub.add_parser("budget", help="show cleared simulated budget and reservations")
    budget_cmd.add_argument("agent_id")
    budget_cmd.add_argument("--currency", default="USD")
    schedules_cmd = sub.add_parser("schedules", help="list recurring expense schedules")
    schedules_cmd.add_argument("--agent-id")
    schedules_cmd.add_argument("--status", choices=["active", "paused", "cancelled"])
    pause_all_cmd = sub.add_parser("pause-all", help="emergency pause every active recurring schedule")
    schedule_cmd = sub.add_parser("schedule", help="manage one recurring expense schedule")
    schedule_cmd.add_argument("action", choices=["pause", "resume", "cancel"])
    schedule_cmd.add_argument("schedule_id")

    template_cmd = sub.add_parser("policy-template", help="write a normalized unsigned policy payload")
    template_cmd.add_argument("--policy-id", required=True)
    template_cmd.add_argument("--version", type=int, required=True)
    template_cmd.add_argument("--owner-id", required=True)
    template_cmd.add_argument("--agent-id", required=True)
    template_cmd.add_argument("--currency", required=True)
    template_cmd.add_argument("--per-transaction-limit-minor", type=int, required=True)
    template_cmd.add_argument("--daily-spend-limit-minor", type=int, required=True)
    template_cmd.add_argument("--destination", action="append", required=True)
    template_cmd.add_argument("--output", type=Path, required=True)

    sign_cmd = sub.add_parser("policy-sign", help="owner-sign and store a policy payload using a local PEM key")
    sign_cmd.add_argument("payload", type=Path)
    sign_cmd.add_argument("--private-key", type=Path, required=True,
                          help="owner-held Ed25519 PEM key; never commit or upload this file")

    args = parser.parse_args()
    try:
        registry, policies, ledger, spending, scheduler = _services(args.data_dir)

        if args.command == "policies":
            rows = policies.list_for_agent(args.agent_id)
            _print_json([{
                "agent_id": row["agent_id"], "owner_id": row["owner_id"],
                "policy_id": row["policy_id"], "version": row["version"],
                "status": row["status"], "currently_authorized": row["currently_authorized"],
                "policy": row["policy"],
            } for row in rows])
        elif args.command == "budget":
            _print_json(spending.budget_summary(args.agent_id, args.currency))
        elif args.command == "schedules":
            _print_json(scheduler.list_schedules(agent_id=args.agent_id, status=args.status))
        elif args.command == "pause-all":
            changed = scheduler.pause_all()
            _print_json({"paused_schedules": changed, "message": "Active recurring schedules are paused locally."})
        elif args.command == "schedule":
            result = getattr(scheduler, args.action)(args.schedule_id)
            _print_json(result)
        elif args.command == "policy-template":
            payload = policies.payload(
                policy_id=args.policy_id, version=args.version, owner_id=args.owner_id,
                agent_id=args.agent_id, currency=args.currency,
                per_transaction_limit_minor=args.per_transaction_limit_minor,
                daily_spend_limit_minor=args.daily_spend_limit_minor,
                allowed_destinations=args.destination,
            )
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("x", encoding="utf-8") as stream:
                json.dump(payload, stream, indent=2, sort_keys=True)
                stream.write("\n")
            _print_json({"output": str(args.output), "status": "unsigned",
                         "next_step": "Review the exact terms, then owner-sign with policy-sign."})
        elif args.command == "policy-sign":
            try:
                from cryptography.hazmat.primitives.serialization import load_pem_private_key
                from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
            except ImportError as exc:
                raise SystemExit("Install identity support: pip install -e '.[identity]'") from exc
            key = load_pem_private_key(args.private_key.read_bytes(), password=None)
            if not isinstance(key, Ed25519PrivateKey):
                raise ValueError("private key must be an unencrypted Ed25519 PEM key")
            payload = json.loads(args.payload.read_text(encoding="utf-8"))
            signature = base64.urlsafe_b64encode(key.sign(_canonical(payload))).decode("ascii").rstrip("=")
            saved = policies.save(payload, signature)
            _print_json({
                "agent_id": saved["agent_id"], "owner_id": saved["owner_id"],
                "policy_id": saved["policy_id"], "version": saved["version"],
                "status": saved["status"], "currently_authorized": saved["currently_authorized"],
                "policy_sha256": saved["policy_sha256"],
            })
        return 0
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

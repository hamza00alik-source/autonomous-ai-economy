"""Local owner console for simulated agent financial controls.

This CLI is intended for trusted local administration only. It is not an
authenticated network API or a public dashboard. It never sends payments.
"""
from __future__ import annotations

import argparse
import base64
import json
import hashlib
import re
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


def _cloud_policy_envelope(registry, payload: dict, key, operator_id: str) -> dict:
    """Create a cloud-compatible envelope without exporting private key material."""
    required = {
        "policy_id", "version", "owner_id", "agent_id", "currency",
        "per_transaction_limit_minor", "daily_spend_limit_minor", "allowed_destinations",
    }
    if not isinstance(payload, dict) or set(payload) != required:
        raise ValueError("cloud policy payload has missing or unexpected fields")
    identifier = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,79}$")
    for field in ("policy_id", "owner_id", "agent_id"):
        if not isinstance(payload[field], str) or not identifier.fullmatch(payload[field]):
            raise ValueError(f"invalid {field}")
    if not isinstance(operator_id, str) or not identifier.fullmatch(operator_id):
        raise ValueError("invalid cloud operator_id")
    if isinstance(payload["version"], bool) or not isinstance(payload["version"], int) or payload["version"] < 1:
        raise ValueError("version must be a positive integer")
    if not isinstance(payload["currency"], str) or not re.fullmatch(r"[A-Z]{3}", payload["currency"]):
        raise ValueError("currency must be a three-letter uppercase code")
    for field in ("per_transaction_limit_minor", "daily_spend_limit_minor"):
        value = payload[field]
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 9_007_199_254_740_991:
            raise ValueError(f"{field} must be a positive safe integer")
    if payload["per_transaction_limit_minor"] > payload["daily_spend_limit_minor"]:
        raise ValueError("per-transaction limit cannot exceed daily limit")
    destinations = payload["allowed_destinations"]
    if (not isinstance(destinations, list) or not 1 <= len(destinations) <= 50
            or any(not isinstance(item, str) or not item or item.strip() != item
                   or len(item) > 256 or "*" in item for item in destinations)
            or len(set(destinations)) != len(destinations)):
        raise ValueError("allowed_destinations must contain unique exact destination strings")

    owner = registry.get(payload["owner_id"])
    agent = registry.get(payload["agent_id"])
    if (not owner or owner.get("status") != "active"
            or owner.get("participant_type") not in {"human", "organization"}
            or not owner.get("public_key")):
        raise ValueError("active local owner with an enrolled public key is required")
    if (not agent or agent.get("status") != "active"
            or agent.get("participant_type") != "agent"
            or agent.get("operator_id") != payload["owner_id"]):
        raise ValueError("active local agent must be operated by this owner")

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("private key must be Ed25519")
    public_raw = key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    local_public = base64.urlsafe_b64encode(public_raw).decode("ascii").rstrip("=")
    if local_public != owner["public_key"]:
        raise ValueError("private key does not match the enrolled local owner public key")

    canonical_payload = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    signature = base64.urlsafe_b64encode(
        key.sign(canonical_payload.encode("utf-8"))
    ).decode("ascii").rstrip("=")
    fingerprint_input = json.dumps(
        {"crv": "Ed25519", "kty": "OKP", "x": local_public},
        separators=(",", ":"), ensure_ascii=False,
    )
    fingerprint = hashlib.sha256(fingerprint_input.encode("utf-8")).hexdigest()
    return {
        "policy": payload,
        "canonical_payload": canonical_payload,
        "signature_base64url": signature,
        "signer_key_fingerprint": fingerprint,
    }

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

    cloud_sign_cmd = sub.add_parser(
        "cloud-policy-sign",
        help="sign a cloud-format policy locally and export a public signed envelope",
    )
    cloud_sign_cmd.add_argument("payload", type=Path)
    cloud_sign_cmd.add_argument("--private-key", type=Path, required=True,
                                help="owner-held Ed25519 PEM key; never upload or commit it")
    cloud_sign_cmd.add_argument("--operator-id", required=True,
                                help="pre-enrolled cloud operator participant ID")
    cloud_sign_cmd.add_argument("--output", type=Path, required=True,
                                help="new envelope file; existing files are never overwritten")

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
        elif args.command == "cloud-policy-sign":
            try:
                from cryptography.hazmat.primitives.serialization import load_pem_private_key
                from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
            except ImportError as exc:
                raise SystemExit("Install identity support: pip install -e '.[identity]'") from exc
            key = load_pem_private_key(args.private_key.read_bytes(), password=None)
            if not isinstance(key, Ed25519PrivateKey):
                raise ValueError("private key must be an unencrypted Ed25519 PEM key")
            payload = json.loads(args.payload.read_text(encoding="utf-8"))
            envelope = _cloud_policy_envelope(registry, payload, key, args.operator_id)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("x", encoding="utf-8") as stream:
                json.dump(envelope, stream, indent=2, sort_keys=True, ensure_ascii=False)
                stream.write("\\n")
            _print_json({
                "output": str(args.output),
                "status": "signed_cloud_envelope",
                "operator_id": args.operator_id,
                "private_key_uploaded": False,
                "next_step": "Review the envelope, then submit it through the authenticated owner dashboard.",
            })
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

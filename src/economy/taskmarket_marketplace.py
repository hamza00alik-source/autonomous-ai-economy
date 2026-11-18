"""Read-only Taskmarket Base task discovery and conservative qualification.

Taskmarket API metadata is not independent proof of an on-chain escrow or payout.
This adapter never registers an identity, connects a wallet, signs, claims,
submits, posts, or pays.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
import re
import sqlite3
from pathlib import Path
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

BASE_URL = "https://api.taskmarket.dev"
CHAIN_ID = 8453
NETWORK = "eip155:8453"
MAX_RESPONSE_BYTES = 3_000_000
TASK_ID_RE = re.compile(r"^0x[a-fA-F0-9]{64}$")
TX_RE = re.compile(r"^0x[a-fA-F0-9]{64}$")


def _usdc(base_units: object) -> str | None:
    try:
        value = Decimal(str(base_units)) / Decimal(1_000_000)
        if value < 0:
            return None
        return f"{value:.6f}"
    except (InvalidOperation, TypeError, ValueError):
        return None


@dataclass(frozen=True)
class TaskmarketLead:
    task_id: str
    reference_code: str
    title: str
    description: str
    chain_id: int
    mode: str
    status: str
    phase: str
    reward_base_units: str
    reward_usdc: str | None
    net_reward_usdc: str | None
    escrow_tx_hash: str | None
    escrow_tracked: bool
    escrow_booked_base_units: str | None
    submission_count: int
    award_count: int
    expiry_time: str | None
    submission_window_open: bool
    stake_required: bool
    stake_bps: int
    platform_fee_bps: int
    tags: tuple[str, ...]
    requester_actor_type: str
    source: str = "taskmarket"
    payment_verified: bool = False
    escrow_verified_onchain: bool = False
    escrow_verification_status: str = "not_checked"
    escrow_verified_amount_base_units: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


class TaskmarketPublicTasks:
    """Read-only Base mainnet public task API client."""

    def __init__(self, *, timeout_seconds: float = 12, fetcher=None):
        if not 1 <= timeout_seconds <= 30:
            raise ValueError("timeout_seconds must be between 1 and 30")
        self.timeout_seconds = timeout_seconds
        self._fetcher = fetcher or self._fetch

    @staticmethod
    def _fetch(url: str, timeout: float) -> bytes:
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname != "api.taskmarket.dev":
            raise ValueError("only HTTPS api.taskmarket.dev is allowed")
        request = Request(url, headers={
            "Accept": "application/json",
            "User-Agent": "AutonomousAIEconomy/0.1 read-only-task-discovery",
        })
        with urlopen(request, timeout=timeout) as response:
            final = urlparse(response.geturl())
            if final.scheme != "https" or final.hostname != "api.taskmarket.dev":
                raise ValueError("Taskmarket response host rejected")
            body = response.read(MAX_RESPONSE_BYTES + 1)
        if len(body) > MAX_RESPONSE_BYTES:
            raise ValueError("Taskmarket response exceeds 3 MB safety limit")
        return body

    def _json(self, url: str):
        payload = json.loads(self._fetcher(url, self.timeout_seconds))
        return payload

    @staticmethod
    def _parse(row: dict) -> TaskmarketLead | None:
        task_id = row.get("id")
        if not isinstance(task_id, str) or not TASK_ID_RE.fullmatch(task_id):
            return None
        reward = str(row.get("reward") or "")
        reward_usdc = _usdc(reward)
        escrow = row.get("escrow") if isinstance(row.get("escrow"), dict) else {}
        tx_hash = row.get("escrowTxHash")
        if not isinstance(tx_hash, str) or not TX_RE.fullmatch(tx_hash):
            tx_hash = None
        booked = escrow.get("booked")
        booked = str(booked) if booked is not None else None
        try:
            submissions = max(0, int(row.get("submissionCount") or 0))
            awards = max(0, int(row.get("awardCount") or 0))
            stake_bps = max(0, int(row.get("stakeBps") or 0))
            fee_bps = max(0, int(row.get("platformFeeBps") or 0))
            chain_id = int(row.get("chainId") or 0)
        except (TypeError, ValueError):
            return None
        tags = row.get("tags") if isinstance(row.get("tags"), list) else []
        description = str(row.get("description") or "")
        return TaskmarketLead(
            task_id=task_id,
            reference_code=str(row.get("referenceCode") or "")[:40],
            title=description.splitlines()[0][:300] if description else "Untitled task",
            description=description[:20000],
            chain_id=chain_id,
            mode=str(row.get("mode") or "unknown")[:30],
            status=str(row.get("status") or "unknown")[:30],
            phase=str(row.get("phase") or "unknown")[:40],
            reward_base_units=reward,
            reward_usdc=reward_usdc,
            net_reward_usdc=_usdc(row.get("netReward")),
            escrow_tx_hash=tx_hash,
            escrow_tracked=escrow.get("tracked") is True,
            escrow_booked_base_units=booked,
            submission_count=submissions,
            award_count=awards,
            expiry_time=str(row.get("expiryTime")) if row.get("expiryTime") else None,
            submission_window_open=row.get("submissionWindowOpen") is True,
            stake_required=row.get("stakeRequired") is True,
            stake_bps=stake_bps,
            platform_fee_bps=fee_bps,
            tags=tuple(str(x)[:80] for x in tags if isinstance(x, str))[:30],
            requester_actor_type=str(row.get("requesterActorType") or "unknown")[:30],
        )

    def search(self, *, limit: int = 100) -> list[TaskmarketLead]:
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        url = BASE_URL + "/api/tasks?" + urlencode({
            "chainId": CHAIN_ID, "status": "open", "limit": limit, "sort": "newest",
        })
        payload = self._json(url)
        rows = payload.get("tasks") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            raise ValueError("unexpected Taskmarket task-list schema")
        result = []
        for row in rows:
            if not isinstance(row, dict) or row.get("status") != "open":
                continue
            lead = self._parse(row)
            if lead is not None and lead.chain_id == CHAIN_ID:
                result.append(lead)
        return result

    def get_task(self, task_id: str) -> dict:
        if not isinstance(task_id, str) or not TASK_ID_RE.fullmatch(task_id):
            raise ValueError("task_id must be a 32-byte hex task ID")
        url = BASE_URL + "/api/tasks/" + task_id + "?" + urlencode({"chainId": CHAIN_ID})
        payload = self._json(url)
        if not isinstance(payload, dict) or payload.get("id") != task_id:
            raise ValueError("Taskmarket task detail ID mismatch or invalid schema")
        if int(payload.get("chainId") or 0) != CHAIN_ID:
            raise ValueError("Taskmarket task is not on Base mainnet")
        return payload


class BaseEscrowReceiptVerifier:
    """Verify Taskmarket EscrowFunded events against Base public JSON-RPC."""

    RPC_URL = "https://mainnet.base.org"
    DIAMOND = "0xddc6cc3e4d11c1f3527b867c7dad4ed9869c33f7"
    ESCROW_FUNDED_TOPIC = "0x201d660f753914e19eddd41fa59c8765f90e47e94e92d03ea727a9280636ed79"

    def __init__(self, *, timeout_seconds: float = 12, rpc_fetcher=None):
        if not 1 <= timeout_seconds <= 30:
            raise ValueError("timeout_seconds must be between 1 and 30")
        self.timeout_seconds = timeout_seconds
        self._rpc_fetcher = rpc_fetcher or self._post_rpc

    @staticmethod
    def _post_rpc(url: str, body: bytes, timeout: float) -> bytes:
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname != "mainnet.base.org":
            raise ValueError("only the official public Base RPC host is allowed")
        request = Request(url, data=body, headers={
            "Accept": "application/json", "Content-Type": "application/json",
            "User-Agent": "AutonomousAIEconomy/0.1 read-only-escrow-verifier",
        }, method="POST")
        with urlopen(request, timeout=timeout) as response:
            final = urlparse(response.geturl())
            if final.scheme != "https" or final.hostname != "mainnet.base.org":
                raise ValueError("Base RPC response host rejected")
            data = response.read(1_000_001)
        if len(data) > 1_000_000:
            raise ValueError("Base RPC response exceeds 1 MB")
        return data

    def verify(self, task_id: str, tx_hash: str | None, expected_amount_base_units: str) -> dict:
        if not isinstance(task_id, str) or not TASK_ID_RE.fullmatch(task_id):
            return {"verified": False, "status": "invalid_task_id"}
        if not isinstance(tx_hash, str) or not TX_RE.fullmatch(tx_hash):
            return {"verified": False, "status": "missing_escrow_transaction"}
        try:
            expected = int(expected_amount_base_units)
            if expected <= 0:
                raise ValueError
        except (TypeError, ValueError):
            return {"verified": False, "status": "invalid_expected_escrow_amount"}
        body = json.dumps({
            "jsonrpc": "2.0", "id": 1, "method": "eth_getTransactionReceipt",
            "params": [tx_hash],
        }).encode()
        try:
            response = json.loads(self._rpc_fetcher(self.RPC_URL, body, self.timeout_seconds))
        except Exception as exc:
            return {"verified": False, "status": "rpc_error:" + type(exc).__name__}
        receipt = response.get("result") if isinstance(response, dict) else None
        if not isinstance(receipt, dict):
            return {"verified": False, "status": "receipt_not_found"}
        if str(receipt.get("transactionHash", "")).lower() != tx_hash.lower():
            return {"verified": False, "status": "receipt_transaction_hash_mismatch"}
        if str(receipt.get("status", "")).lower() != "0x1":
            return {"verified": False, "status": "transaction_not_successful"}
        logs = receipt.get("logs") if isinstance(receipt.get("logs"), list) else []
        for log in logs:
            if not isinstance(log, dict) or str(log.get("address", "")).lower() != self.DIAMOND:
                continue
            topics = log.get("topics") if isinstance(log.get("topics"), list) else []
            if (len(topics) < 2 or str(topics[0]).lower() != self.ESCROW_FUNDED_TOPIC
                    or str(topics[1]).lower() != task_id.lower()):
                continue
            data = str(log.get("data", ""))
            if not re.fullmatch(r"0x[0-9a-fA-F]{128}", data):
                continue
            amount = int(data[2:66], 16)
            component = int(data[66:130], 16)
            if component != 0:
                continue
            return {
                "verified": amount == expected,
                "status": "verified" if amount == expected else "escrow_amount_mismatch",
                "amount_base_units": str(amount),
                "expected_amount_base_units": str(expected),
                "component": component,
                "task_id": task_id,
                "transaction_hash": tx_hash,
            }
        return {"verified": False, "status": "escrow_funded_event_not_found"}

    def verify_lead(self, lead: TaskmarketLead) -> TaskmarketLead:
        result = self.verify(lead.task_id, lead.escrow_tx_hash, lead.reward_base_units)
        return replace(
            lead,
            escrow_verified_onchain=result.get("verified") is True,
            escrow_verification_status=str(result.get("status") or "unknown"),
            escrow_verified_amount_base_units=result.get("amount_base_units"),
        )


class TaskmarketTaskEvaluator:
    """Rejects split, promotional, off-platform and crowded tasks by default."""

    SPLIT_RE = re.compile(
        r"split equally|share the full pool|first\s+\d+\s+(?:qualifying\s+)?agents|"
        r"one award per|up to\s+\d+\s+(?:accepted|qualifying)", re.I,
    )
    PROMO_RE = re.compile(
        r"public (?:post|reply|conversation)|paid promotion|promotional post|"
        r"publish (?:one )?(?:useful )?(?:accurate )?reply|social media|post on your own account", re.I,
    )
    OFF_PLATFORM_RE = re.compile(
        r"off-platform|paid off-platform|listing deposit|not a per-worker payout|"
        r"BEP-?20|FLAPJAX|first-timers only|"
        r"worker address.{0,40}sign|wallet age|agent ID.{0,30}7 days", re.I,
    )

    def __init__(self, *, minimum_reward_usdc: str = "1.00",
                 maximum_submissions: int = 5):
        self.minimum_reward = Decimal(minimum_reward_usdc)
        if self.minimum_reward < 0:
            raise ValueError("minimum_reward_usdc cannot be negative")
        if not 0 <= maximum_submissions <= 10000:
            raise ValueError("maximum_submissions must be between 0 and 10000")
        self.maximum_submissions = maximum_submissions

    def evaluate(self, lead: TaskmarketLead | dict, detail: dict | None = None) -> dict:
        data = lead.to_dict() if isinstance(lead, TaskmarketLead) else dict(lead)
        task = detail or data
        reasons = []
        desc = str(task.get("description") or data.get("description") or "")
        reward_text = _usdc(task.get("reward", data.get("reward_base_units", "0")))
        net_reward_text = _usdc(task.get("netReward", data.get("net_reward_usdc", "0")))
        reward = Decimal(reward_text) if reward_text is not None else None
        net_reward = Decimal(net_reward_text) if net_reward_text is not None else None
        escrow = task.get("escrow") if isinstance(task.get("escrow"), dict) else {}
        tx_hash = task.get("escrowTxHash", data.get("escrow_tx_hash"))
        booked = str(escrow.get("booked", data.get("escrow_booked_base_units", "")))
        reward_raw = str(task.get("reward", data.get("reward_base_units", "")))

        if int(task.get("chainId", data.get("chain_id", 0)) or 0) != CHAIN_ID:
            reasons.append("unsupported_network")
        if task.get("status", data.get("status")) != "open":
            reasons.append("task_not_open")
        if task.get("mode", data.get("mode")) != "bounty":
            reasons.append("unsupported_task_mode")
        if not TASK_ID_RE.fullmatch(str(task.get("id", data.get("task_id", "")))):
            reasons.append("invalid_task_id")
        if not isinstance(tx_hash, str) or not TX_RE.fullmatch(tx_hash):
            reasons.append("escrow_transaction_not_reported")
        if escrow.get("tracked", data.get("escrow_tracked")) is not True:
            reasons.append("escrow_not_tracked_by_platform")
        if not reward_raw or booked != reward_raw:
            reasons.append("escrow_booked_amount_mismatch")
        if data.get("escrow_verified_onchain") is not True:
            reasons.append("escrow_not_independently_verified")
        if str(data.get("escrow_verified_amount_base_units") or "") != reward_raw:
            reasons.append("onchain_escrow_amount_mismatch")
        if reward is None or reward < self.minimum_reward:
            reasons.append("reward_below_minimum_or_invalid")
        if net_reward is None or net_reward < self.minimum_reward:
            reasons.append("net_reward_below_minimum_or_invalid")
        if task.get("stakeRequired", data.get("stake_required")) is True or int(task.get("stakeBps", data.get("stake_bps", 0)) or 0) > 0:
            reasons.append("worker_stake_or_deposit_required")
        if task.get("submissionWindowOpen", data.get("submission_window_open")) is not True:
            reasons.append("submission_window_closed")
        try:
            count = int(task.get("submissionCount", data.get("submission_count", 0)) or 0)
        except (TypeError, ValueError):
            count = self.maximum_submissions + 1
        if count > self.maximum_submissions:
            reasons.append("too_many_competing_submissions")
        expiry = task.get("expiryTime", data.get("expiry_time"))
        if expiry:
            try:
                expiry_dt = datetime.fromisoformat(str(expiry).replace("Z", "+00:00"))
                if expiry_dt <= datetime.now(timezone.utc):
                    reasons.append("task_expired")
            except ValueError:
                reasons.append("invalid_expiry_time")
        if self.SPLIT_RE.search(desc):
            reasons.append("split_reward_pool")
        if self.PROMO_RE.search(desc):
            reasons.append("public_promotion_or_outreach_required")
        if self.OFF_PLATFORM_RE.search(desc):
            reasons.append("off_platform_or_token_payout_terms")
        if not desc.strip() or len(desc.strip()) < 120:
            reasons.append("insufficient_task_scope")
        if "accept" not in desc.lower() and "deliver" not in desc.lower() and "submit" not in desc.lower():
            reasons.append("acceptance_or_delivery_terms_missing")
        reasons = list(dict.fromkeys(reasons))
        return {
            "task_id": task.get("id", data.get("task_id")),
            "reference_code": task.get("referenceCode", data.get("reference_code")),
            "state": "qualified_for_local_draft" if not reasons else "rejected_or_needs_review",
            "score": max(0, 100 - 15 * len(reasons)),
            "reasons": reasons,
            "reward_usdc": str(reward) if reward is not None else None,
            "net_reward_usdc": str(net_reward) if net_reward is not None else None,
            "submission_count": count,
            "escrow_status": (
                "onchain_verified" if data.get("escrow_verified_onchain") is True
                else "platform_reported_only" if tx_hash and escrow.get("tracked", data.get("escrow_tracked"))
                else "not_reported"
            ),
            "payment_verified": False,
            "claim_allowed": False,
            "external_actions": 0,
        }


class TaskmarketOpportunityStore:
    """Local SQLite audit trail for read-only task discovery and evaluation."""

    def __init__(self, path: str | Path = "./data/taskmarket-opportunities.sqlite3"):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS taskmarket_opportunities (
                    task_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    reward_base_units TEXT NOT NULL,
                    submission_count INTEGER NOT NULL,
                    payload_json TEXT NOT NULL,
                    evaluation_json TEXT,
                    discovered_at TEXT NOT NULL
                )
            """)

    def save_many(self, leads: list[TaskmarketLead], evaluator: TaskmarketTaskEvaluator | None = None) -> dict:
        now = datetime.now(timezone.utc).isoformat()
        eligible = 0
        onchain_verified = 0
        with sqlite3.connect(self.path) as db:
            for lead in leads:
                payload = lead.to_dict()
                evaluation = evaluator.evaluate(lead) if evaluator else None
                if payload.get("escrow_verified_onchain") is True:
                    onchain_verified += 1
                if evaluation and evaluation["state"] == "qualified_for_local_draft":
                    eligible += 1
                db.execute("""
                    INSERT INTO taskmarket_opportunities
                    (task_id,status,reward_base_units,submission_count,payload_json,evaluation_json,discovered_at)
                    VALUES(?,?,?,?,?,?,?)
                    ON CONFLICT(task_id) DO UPDATE SET
                      status=excluded.status,reward_base_units=excluded.reward_base_units,
                      submission_count=excluded.submission_count,payload_json=excluded.payload_json,
                      evaluation_json=excluded.evaluation_json,discovered_at=excluded.discovered_at
                """, (lead.task_id, lead.status, lead.reward_base_units, lead.submission_count,
                      json.dumps(payload, sort_keys=True), json.dumps(evaluation, sort_keys=True) if evaluation else None, now))
        return {"fetched": len(leads), "saved": len(leads), "onchain_escrows_verified": onchain_verified,
                "qualified_for_local_draft": eligible, "claims": 0, "submissions": 0, "payments": 0}

    def list_opportunities(self, *, limit: int = 50, qualified_only: bool = False) -> list[dict]:
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        query = "SELECT payload_json,evaluation_json,discovered_at FROM taskmarket_opportunities"
        if qualified_only:
            query += " WHERE evaluation_json LIKE '%qualified_for_local_draft%'"
        query += " ORDER BY discovered_at DESC LIMIT ?"
        with sqlite3.connect(self.path) as db:
            db.row_factory = sqlite3.Row
            rows = db.execute(query, (limit,)).fetchall()
        return [{
            "task": json.loads(row["payload_json"]),
            "evaluation": json.loads(row["evaluation_json"]) if row["evaluation_json"] else None,
            "discovered_at": row["discovered_at"],
        } for row in rows]

"""Cross-marketplace revenue intelligence for the Autonomous AI Economy.

This module combines existing read-only marketplace adapters into one ranked
pipeline. It never registers, claims, submits, publishes, signs, or transfers.
A candidate can become ready for owner review only after independent escrow
verification and a complete source-specific scope evaluation.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import sqlite3
from typing import Any


@dataclass(frozen=True)
class RevenueCandidate:
    source: str
    external_id: str
    title: str
    url: str | None
    currency: str | None
    gross_reward: str | None
    net_reward: str | None
    status: str
    priority_score: int
    fit_score: int
    evidence_confidence: int
    escrow_verified: bool
    payment_verified: bool
    reasons: tuple[str, ...]
    discovered_at: str
    claim_allowed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class RevenueOpportunityStore:
    """Small durable shortlist; local records are not payment evidence."""

    def __init__(self, path: str | Path = "./data/revenue-opportunities.sqlite3"):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS revenue_opportunities (
                    source TEXT NOT NULL,
                    external_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    priority_score INTEGER NOT NULL,
                    payload_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(source, external_id)
                )
            """)

    def save_many(self, candidates: list[RevenueCandidate]) -> int:
        now = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self.path) as db:
            for candidate in candidates:
                db.execute("""
                    INSERT INTO revenue_opportunities
                    (source,external_id,status,priority_score,payload_json,updated_at)
                    VALUES(?,?,?,?,?,?)
                    ON CONFLICT(source,external_id) DO UPDATE SET
                      status=excluded.status,
                      priority_score=excluded.priority_score,
                      payload_json=excluded.payload_json,
                      updated_at=excluded.updated_at
                """, (
                    candidate.source, candidate.external_id, candidate.status,
                    candidate.priority_score,
                    json.dumps(candidate.to_dict(), sort_keys=True, separators=(",", ":")),
                    now,
                ))
        return len(candidates)

    def list(self, *, limit: int = 50, ready_only: bool = False) -> list[dict]:
        if not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")
        query = "SELECT payload_json FROM revenue_opportunities"
        params: tuple[Any, ...] = ()
        if ready_only:
            query += " WHERE status='ready_for_owner_review'"
        query += " ORDER BY CASE status WHEN 'ready_for_owner_review' THEN 0 ELSE 1 END, priority_score DESC, updated_at DESC LIMIT ?"
        params = (limit,)
        with sqlite3.connect(self.path) as db:
            rows = db.execute(query, params).fetchall()
        return [json.loads(row[0]) for row in rows]


def _amount(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        amount = Decimal(str(value).replace(",", "").replace("$", "").strip())
        return amount if amount >= 0 else None
    except (InvalidOperation, TypeError, ValueError):
        return None


def _priority(fit_score: int, confidence: int, reward: Any) -> int:
    amount = _amount(reward)
    reward_score = min(100, int(amount * 10)) if amount is not None else 0
    return max(0, min(100, round(fit_score * 0.55 + confidence * 0.35 + reward_score * 0.10)))


class RevenueEngine:
    """Federate read-only paid-task sources and rank by fit and payment evidence."""

    def __init__(
        self,
        store: RevenueOpportunityStore,
        *,
        basedagents=None,
        jobbi=None,
        taskmarket=None,
        escrow_verifier=None,
        minimum_basedagents_usdc: str = "0.10",
        minimum_taskmarket_usdc: str = "1.00",
        maximum_taskmarket_submissions: int = 5,
    ):
        from .basedagents_marketplace import BasedAgentsPublicTasks
        from .basedagents_task_evaluator import PaidTaskCapabilityEvaluator
        from .jobbi_gigs import JobbiGigEvaluator, JobbiPublicGigs
        from .taskmarket_marketplace import (
            BaseEscrowReceiptVerifier, TaskmarketPublicTasks, TaskmarketTaskEvaluator,
        )

        self.store = store
        self.basedagents = basedagents or BasedAgentsPublicTasks()
        self.jobbi = jobbi or JobbiPublicGigs()
        self.taskmarket = taskmarket or TaskmarketPublicTasks()
        self.escrow_verifier = escrow_verifier or BaseEscrowReceiptVerifier()
        self.basedagents_evaluator = PaidTaskCapabilityEvaluator(
            minimum_bounty_usdc=minimum_basedagents_usdc
        )
        self.jobbi_evaluator = JobbiGigEvaluator()
        self.taskmarket_evaluator = TaskmarketTaskEvaluator(
            minimum_reward_usdc=minimum_taskmarket_usdc,
            maximum_submissions=maximum_taskmarket_submissions,
        )

    def scan_once(
        self,
        *,
        limit: int = 50,
        verify_limit: int = 25,
        sources: tuple[str, ...] = ("basedagents", "jobbi", "taskmarket"),
    ) -> dict:
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        if not 0 <= verify_limit <= 100:
            raise ValueError("verify_limit must be between 0 and 100")
        allowed = {"basedagents", "jobbi", "taskmarket"}
        if not sources or any(source not in allowed for source in sources):
            raise ValueError("sources must contain supported marketplace names")

        candidates: list[RevenueCandidate] = []
        errors: list[dict[str, str]] = []
        counts: dict[str, int] = {}

        def failed(source: str, exc: Exception) -> None:
            errors.append({"source": source, "error": type(exc).__name__})

        if "basedagents" in sources:
            try:
                leads = self.basedagents.search(limit=limit)
                counts["basedagents"] = len(leads)
                for lead in leads:
                    data = lead.to_dict()
                    reasons: list[str] = []
                    fit = 0
                    gross = data.get("bounty_usdc")
                    try:
                        detail = self.basedagents.get_task(lead.task_id)
                        evaluation = self.basedagents_evaluator.evaluate(data, detail)
                        fit = evaluation.score
                        reasons.extend(evaluation.reasons)
                        payment = self.basedagents.get_task_payment(lead.task_id)
                        escrow = detail.get("escrow") if isinstance(detail.get("escrow"), dict) else {}
                        if not (
                            escrow.get("status") == "funded"
                            and payment.get("verified") is True
                            and payment.get("tx_hash")
                        ):
                            reasons.append("marketplace_payment_not_proven_funded")
                        # The adapter has no independent Base receipt verifier for this venue.
                        reasons.append("independent_escrow_verification_unavailable")
                    except Exception as exc:
                        reasons.append("detail_or_payment_audit_failed:" + type(exc).__name__)
                    reasons = list(dict.fromkeys(reasons))
                    confidence = 25 if data.get("payment_verified") else 0
                    candidates.append(self._candidate(
                        source="basedagents", external_id=lead.task_id,
                        title=lead.title, url=None, currency="USDC",
                        gross=gross, net=None, fit=fit, confidence=confidence,
                        escrow_verified=False, reasons=reasons,
                        status="needs_owner_review",
                    ))
            except Exception as exc:
                failed("basedagents", exc)

        if "jobbi" in sources:
            try:
                gigs = self.jobbi.search(limit=limit)
                counts["jobbi"] = len(gigs)
                for gig in gigs:
                    evaluation = self.jobbi_evaluator.evaluate(gig)
                    reasons = list(evaluation.get("reasons") or [])
                    # Jobbi is an index; its grade and escrow flag are not an independent receipt.
                    reasons.append("original_board_terms_and_escrow_need_independent_review")
                    reasons = list(dict.fromkeys(reasons))
                    fit = max(0, 100 - 10 * len(evaluation.get("reasons") or []))
                    confidence = 50 if (
                        gig.payment_state == "escrowed"
                        and gig.payout_grade in {"A", "B", "B+"}
                    ) else 0
                    candidates.append(self._candidate(
                        source="jobbi", external_id=gig.gig_id,
                        title=gig.title, url=gig.url, currency=gig.currency,
                        gross=gig.reward_amount, net=None, fit=fit,
                        confidence=confidence, escrow_verified=False,
                        reasons=reasons, status="needs_owner_review",
                    ))
            except Exception as exc:
                failed("jobbi", exc)

        if "taskmarket" in sources:
            try:
                leads = self.taskmarket.search(limit=limit)
                counts["taskmarket"] = len(leads)
                for index, lead in enumerate(leads):
                    reasons: list[str] = []
                    fit = 0
                    detail = None
                    verified = False
                    if index < verify_limit:
                        try:
                            lead = self.escrow_verifier.verify_lead(lead)
                            verified = lead.escrow_verified_onchain is True
                            detail = self.taskmarket.get_task(lead.task_id)
                            evaluation = self.taskmarket_evaluator.evaluate(lead, detail)
                            fit = int(evaluation.get("score") or 0)
                            reasons.extend(evaluation.get("reasons") or [])
                        except Exception as exc:
                            reasons.append("detail_or_chain_verification_failed:" + type(exc).__name__)
                    else:
                        reasons.append("chain_verification_deferred_by_scan_limit")
                    reasons = list(dict.fromkeys(reasons))
                    ready = verified and not reasons and detail is not None
                    candidates.append(self._candidate(
                        source="taskmarket", external_id=lead.task_id,
                        title=lead.title, url=None, currency="USDC",
                        gross=lead.reward_usdc, net=lead.net_reward_usdc,
                        fit=fit, confidence=100 if verified else 0,
                        escrow_verified=verified, reasons=reasons,
                        status="ready_for_owner_review" if ready else "needs_owner_review",
                    ))
            except Exception as exc:
                failed("taskmarket", exc)

        self.store.save_many(candidates)
        ordered = sorted(
            candidates,
            key=lambda item: (
                item.status == "ready_for_owner_review",
                item.priority_score,
                _amount(item.net_reward or item.gross_reward) or Decimal("0"),
            ),
            reverse=True,
        )
        return {
            "sources": list(sources),
            "fetched_by_source": counts,
            "candidates_saved": len(candidates),
            "ready_for_owner_review": sum(x.status == "ready_for_owner_review" for x in candidates),
            "needs_owner_review": sum(x.status == "needs_owner_review" for x in candidates),
            "source_errors": errors,
            "top_candidates": [item.to_dict() for item in ordered[:20]],
            "external_claims": 0,
            "submissions": 0,
            "payments": 0,
            "revenue_usdc": "0.00",
            "notice": (
                "Discovery and ranking only. Owner review is still required before any external "
                "commitment. Escrow funding is not agent revenue; revenue remains zero until a "
                "real accepted delivery is paid and independently reconciled."
            ),
        }

    @staticmethod
    def _candidate(
        *,
        source: str,
        external_id: str,
        title: str,
        url: str | None,
        currency: str | None,
        gross: Any,
        net: Any,
        fit: int,
        confidence: int,
        escrow_verified: bool,
        reasons: list[str],
        status: str,
    ) -> RevenueCandidate:
        reward_for_score = net if net is not None else gross
        return RevenueCandidate(
            source=source, external_id=external_id, title=str(title)[:300],
            url=url, currency=currency, gross_reward=str(gross) if gross is not None else None,
            net_reward=str(net) if net is not None else None, status=status,
            priority_score=_priority(fit, confidence, reward_for_score),
            fit_score=max(0, min(100, int(fit))),
            evidence_confidence=max(0, min(100, int(confidence))),
            escrow_verified=bool(escrow_verified), payment_verified=False,
            reasons=tuple(reasons), discovered_at=datetime.now(timezone.utc).isoformat(),
            claim_allowed=False,
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AAE cross-marketplace revenue intelligence")
    parser.add_argument("--data-dir", type=Path, default=Path("./data"))
    sub = parser.add_subparsers(dest="command", required=True)
    scan = sub.add_parser("scan", help="rank paid opportunities across supported agent marketplaces")
    scan.add_argument("--limit", type=int, default=50)
    scan.add_argument("--verify-limit", type=int, default=25)
    scan.add_argument("--sources", nargs="+", choices=("basedagents", "jobbi", "taskmarket"),
                      default=("basedagents", "jobbi", "taskmarket"))
    listing = sub.add_parser("list", help="show the saved cross-marketplace shortlist")
    listing.add_argument("--limit", type=int, default=50)
    listing.add_argument("--ready-only", action="store_true")
    args = parser.parse_args(argv)
    store = RevenueOpportunityStore(args.data_dir / "revenue-opportunities.sqlite3")
    if args.command == "list":
        print(json.dumps(store.list(limit=args.limit, ready_only=args.ready_only), indent=2))
        return 0
    engine = RevenueEngine(store)
    print(json.dumps(engine.scan_once(
        limit=args.limit, verify_limit=args.verify_limit, sources=tuple(args.sources),
    ), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

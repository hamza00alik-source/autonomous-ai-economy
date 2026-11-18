"""Read-only adapter for Jobbi's public index of agent gigs.

Jobbi aggregates third-party listings; it does not claim work, escrow funds,
verify deliverables, or pay agents. Feed fields are untrusted metadata.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import sqlite3
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

BASE_URL = "https://jobbi.org"
FEED_URL = BASE_URL + "/gigs.json"
MAX_RESPONSE_BYTES = 5_000_000
SUPPORTED_CURRENCIES = frozenset({"USD", "USDC"})


@dataclass(frozen=True)
class JobbiGig:
    gig_id: str
    title: str
    url: str
    summary: str
    source: str
    source_name: str
    currency: str | None
    reward_amount: str | None
    payment_rail: str
    payment_state: str
    payout_grade: str
    acceptance: str
    acceptance_type: str
    claims_open: bool
    lane: str = "agent"
    payment_verified: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


class JobbiPublicGigs:
    """Fetch Jobbi's public JSON feed; never visits or acts on board URLs."""

    def __init__(self, *, timeout_seconds: float = 12, fetcher=None):
        if not 1 <= timeout_seconds <= 30:
            raise ValueError("timeout_seconds must be between 1 and 30")
        self.timeout_seconds = timeout_seconds
        self._fetcher = fetcher or self._fetch

    @staticmethod
    def _fetch(url: str, timeout: float) -> bytes:
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname != "jobbi.org":
            raise ValueError("only HTTPS jobbi.org is allowed")
        request = Request(url, headers={
            "Accept": "application/feed+json, application/json",
            "User-Agent": "AutonomousAIEconomy/0.1 public-gig-discovery",
        })
        with urlopen(request, timeout=timeout) as response:
            final = urlparse(response.geturl())
            if final.scheme != "https" or final.hostname != "jobbi.org":
                raise ValueError("response host rejected")
            body = response.read(MAX_RESPONSE_BYTES + 1)
        if len(body) > MAX_RESPONSE_BYTES:
            raise ValueError("Jobbi feed exceeds 5 MB safety limit")
        return body

    def search(self, *, limit: int = 100, source: str | None = None) -> list[JobbiGig]:
        if not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        if source is not None and (not source or len(source) > 80
                or any(ch not in "abcdefghijklmnopqrstuvwxyz0123456789-_" for ch in source)):
            raise ValueError("invalid source filter")
        params = {"lane": "agent", "limit": limit}
        if source:
            params["source"] = source
        url = FEED_URL + "?" + urlencode(params)
        payload = json.loads(self._fetcher(url, self.timeout_seconds))
        if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
            raise ValueError("unexpected Jobbi JSON Feed schema")
        result = []
        seen = set()
        for item in payload["items"]:
            if not isinstance(item, dict):
                continue
            meta = item.get("_jobbi")
            if not isinstance(meta, dict) or meta.get("lane") != "agent":
                continue
            gig_id = item.get("id")
            title = item.get("title")
            link = item.get("url")
            parsed_link = urlparse(link) if isinstance(link, str) else None
            if (not isinstance(gig_id, str) or not gig_id or len(gig_id) > 300
                    or gig_id in seen or not isinstance(title, str)
                    or not isinstance(link, str) or parsed_link.scheme != "https"
                    or not parsed_link.hostname):
                continue
            seen.add(gig_id)
            reward = meta.get("reward") if isinstance(meta.get("reward"), dict) else {}
            currency = reward.get("currency")
            amount = reward.get("amount")
            if currency is not None:
                currency = str(currency).upper()[:20]
            if amount is not None:
                amount = str(amount)[:40]
            result.append(JobbiGig(
                gig_id=gig_id,
                title=title[:300],
                url=link[:2000],
                summary=str(item.get("content_text") or "")[:5000],
                source=str(meta.get("source") or "unknown")[:80],
                source_name=str(meta.get("source_name") or "")[:120],
                currency=currency,
                reward_amount=amount,
                payment_rail=str(reward.get("rail") or "unknown")[:80],
                payment_state=str(meta.get("payment_state") or "unknown")[:40],
                payout_grade=str(meta.get("payout_grade") or "F")[:4],
                acceptance=str(meta.get("acceptance") or "")[:1000],
                acceptance_type=str(meta.get("acceptance_type") or "unknown")[:40],
                claims_open=meta.get("claims_open") is True,
            ))
        return result


def _positive_amount(value: str | None) -> bool:
    try:
        return Decimal(str(value)) > 0
    except (InvalidOperation, TypeError, ValueError):
        return False


class JobbiGigStore:
    """Persistent local shortlist. No task claims, wallet actions, or payments."""

    def __init__(self, path: str | Path = "./data/jobbi-gigs.sqlite3"):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS jobbi_gigs (
                    gig_id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    currency TEXT,
                    reward_amount TEXT,
                    payment_state TEXT NOT NULL,
                    claims_open INTEGER NOT NULL,
                    payload_json TEXT NOT NULL,
                    discovered_at TEXT NOT NULL
                )
            """)

    def save_many(self, gigs: list[JobbiGig]) -> dict:
        now = datetime.now(timezone.utc).isoformat()
        saved = 0
        review = 0
        with sqlite3.connect(self.path) as db:
            for gig in gigs:
                payload = json.dumps(gig.to_dict(), sort_keys=True, separators=(",", ":"))
                db.execute("""
                    INSERT INTO jobbi_gigs
                    (gig_id,source,currency,reward_amount,payment_state,claims_open,payload_json,discovered_at)
                    VALUES(?,?,?,?,?,?,?,?)
                    ON CONFLICT(gig_id) DO UPDATE SET
                      source=excluded.source,currency=excluded.currency,
                      reward_amount=excluded.reward_amount,payment_state=excluded.payment_state,
                      claims_open=excluded.claims_open,payload_json=excluded.payload_json
                """, (gig.gig_id, gig.source, gig.currency, gig.reward_amount,
                      gig.payment_state, int(gig.claims_open), payload, now))
                saved += 1
                if (gig.claims_open and gig.currency in SUPPORTED_CURRENCIES
                        and _positive_amount(gig.reward_amount)
                        and gig.payment_state in {"escrowed", "promised"}):
                    review += 1
        return {"saved": saved, "review_required": review, "claims": 0, "payments": 0}

    def list_review_required(self, limit: int = 50) -> list[dict]:
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        with sqlite3.connect(self.path) as db:
            db.row_factory = sqlite3.Row
            rows = db.execute("""
                SELECT payload_json,discovered_at FROM jobbi_gigs
                WHERE claims_open=1 AND currency IN ('USD','USDC')
                  AND reward_amount IS NOT NULL AND CAST(reward_amount AS REAL) > 0
                  AND payment_state IN ('escrowed','promised')
                ORDER BY CASE payment_state WHEN 'escrowed' THEN 0 ELSE 1 END,
                         discovered_at DESC LIMIT ?
            """, (limit,)).fetchall()
        return [{**json.loads(row["payload_json"]), "discovered_at": row["discovered_at"]}
                for row in rows]

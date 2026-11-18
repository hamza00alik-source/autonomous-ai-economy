"""Read-only public discovery for make.fun AI coding bounties.

No keypair, API key, wallet, claim, entry, submission, or payment is used.
The returned records are leads only: a competition listing is not a promise
that this agent can place or receive a reward.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
import json
from typing import Callable
from urllib.error import URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

BASE_URL = "https://make.fun"
MAX_RESPONSE_BYTES = 1_000_000


@dataclass(frozen=True)
class MakeFunBounty:
    slug: str
    title: str
    description: str
    category: str
    reward_usdc: str | None
    deadline: str | None
    status: str
    paid_places: int | None
    entry_fee_usdc: str | None
    escrow_status: str
    source_url: str
    source: str = "make.fun"
    payment_verified: bool = False
    entry_allowed: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


class MakeFunPublicBounties:
    """Fetch public open competitions from make.fun without authentication."""

    def __init__(self, *, timeout_seconds: float = 12,
                 fetcher: Callable[[str, float], bytes] | None = None):
        if not 1 <= timeout_seconds <= 30:
            raise ValueError("timeout_seconds must be between 1 and 30")
        self.timeout_seconds = timeout_seconds
        self._fetcher = fetcher or self._fetch

    @staticmethod
    def _fetch(url: str, timeout: float) -> bytes:
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname != "make.fun":
            raise ValueError("only HTTPS make.fun is allowed")
        request = Request(url, headers={
            "Accept": "application/json",
            "User-Agent": "AutonomousAIEconomy/0.1 public-bounty-discovery",
        })
        with urlopen(request, timeout=timeout) as response:
            final = urlparse(response.geturl())
            if final.scheme != "https" or final.hostname != "make.fun":
                raise URLError("response host rejected")
            body = response.read(MAX_RESPONSE_BYTES + 1)
        if len(body) > MAX_RESPONSE_BYTES:
            raise ValueError("competition response exceeds 1 MB safety limit")
        return body

    @staticmethod
    def _amount(value) -> str | None:
        if value is None:
            return None
        if isinstance(value, dict):
            value = value.get("amount") or value.get("amount_usdc") or value.get("value")
        if isinstance(value, (int, float, str)):
            try:
                amount = Decimal(str(value).replace("$", "").replace(",", "").replace("USDC", "").strip())
                if amount < 0:
                    return None
                return format(amount, "f")
            except (InvalidOperation, ValueError):
                return None
        return None

    def search(self, *, limit: int = 50) -> list[MakeFunBounty]:
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        url = BASE_URL + "/api/competitions?" + urlencode({"status": "open", "limit": limit})
        payload = json.loads(self._fetcher(url, self.timeout_seconds))
        rows = payload if isinstance(payload, list) else (
            payload.get("competitions") or payload.get("items") or payload.get("data") or []
            if isinstance(payload, dict) else []
        )
        if not isinstance(rows, list):
            raise ValueError("unexpected make.fun competition response schema")
        results = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            slug = row.get("slug") or row.get("id")
            title = row.get("title") or row.get("name")
            status = str(row.get("status") or "unknown").lower()
            if not isinstance(slug, str) or not slug or not isinstance(title, str) or status != "open":
                continue
            rewards = row.get("rewards") or row.get("prizes")
            reward = row.get("reward_usdc") or row.get("reward") or row.get("total_reward")
            paid_places = row.get("paid_places") or row.get("places_paid")
            if paid_places is None and isinstance(rewards, list):
                paid_places = len(rewards)
            try:
                paid_places = int(paid_places) if paid_places is not None else None
                if paid_places is not None and paid_places < 0:
                    paid_places = None
            except (TypeError, ValueError):
                paid_places = None
            fee = row.get("entry_fee_usdc") or row.get("entry_fee")
            escrow = row.get("escrow_status") or ("unknown" if not row.get("escrow") else "listed")
            results.append(MakeFunBounty(
                slug=slug[:180], title=title[:300],
                description=str(row.get("description") or row.get("summary") or "")[:6000],
                category=str(row.get("category") or "unknown")[:80],
                reward_usdc=self._amount(reward),
                deadline=str(row.get("deadline") or row.get("ends_at") or "")[:100] or None,
                status="open", paid_places=paid_places,
                entry_fee_usdc=self._amount(fee),
                escrow_status=str(escrow)[:80],
                source_url=f"{BASE_URL}/bounties/{slug}",
            ))
        return results

"""Evidence-readiness ranking, not a demand or revenue prediction."""
from __future__ import annotations

from dataclasses import dataclass

from .opportunities import EvidenceKind, Opportunity


@dataclass(frozen=True)
class ReadinessResult:
    title: str
    score: int
    present_categories: tuple[str, ...]
    missing_categories: tuple[str, ...]
    independent_source_count: int
    label: str = "evidence_readiness_only"

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "readiness_score": self.score,
            "label": self.label,
            "present_categories": list(self.present_categories),
            "missing_categories": list(self.missing_categories),
            "independent_source_count": self.independent_source_count,
            "warning": "This score measures documentation completeness only. It does not estimate demand, sales, or profitability.",
        }


_WEIGHTS = {
    EvidenceKind.BUYER_SIGNAL: 35,
    EvidenceKind.COMPETITOR: 20,
    EvidenceKind.COST: 20,
    EvidenceKind.LEGAL_OR_POLICY: 15,
    EvidenceKind.MARKET_CONTEXT: 5,
}


def rank_readiness(opportunities: list[Opportunity]) -> list[ReadinessResult]:
    results = []
    for opportunity in opportunities:
        independent = [e for e in opportunity.evidence if e.independent_source and not e.validate()]
        present = {e.kind for e in independent}
        score = sum(weight for kind, weight in _WEIGHTS.items() if kind in present)
        urls = {e.url for e in independent}
        if len(urls) >= 2:
            score += 5
        missing = tuple(sorted(kind.value for kind in _WEIGHTS if kind not in present))
        results.append(ReadinessResult(
            title=opportunity.title,
            score=min(score, 100),
            present_categories=tuple(sorted(kind.value for kind in present)),
            missing_categories=missing,
            independent_source_count=len(urls),
        ))
    return sorted(results, key=lambda item: (-item.score, item.title.casefold()))

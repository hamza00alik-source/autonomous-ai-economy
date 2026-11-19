from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from economy.revenue_engine import RevenueEngine, RevenueOpportunityStore
from economy.basedagents_marketplace import PaidTaskLead
from economy.jobbi_gigs import JobbiGig
from economy.taskmarket_marketplace import TaskmarketLead


class FakeBasedAgents:
    def search(self, *, limit):
        return [PaidTaskLead(
            task_id="based-1", title="Research report", description="A research task",
            category="research", bounty_usdc="5.00", network="eip155:8453",
            status="open", claimable=True,
        )]

    def get_task(self, task_id):
        return {
            "task_id": task_id, "title": "Research report",
            "description": "Prepare a detailed research report.",
            "category": "research", "status": "open", "claimable": True,
            "expected_output": "Markdown report",
            "acceptance_criteria": ["Cite sources"],
            "bounty": {"amount_display": "5.00", "network": "eip155:8453"},
            "escrow": {"status": "funded"},
        }

    def get_task_payment(self, task_id):
        return {"task_id": task_id, "verified": True, "tx_hash": "0x" + "a" * 64}


class FakeJobbi:
    def search(self, *, limit):
        return [JobbiGig(
            gig_id="jobbi-1", title="Prepare a data report",
            url="https://example.test/gig/1", summary="Produce a report",
            source="test", source_name="Test board", currency="USDC",
            reward_amount="4.00", payment_rail="x402", payment_state="escrowed",
            payout_grade="A", acceptance="Accepted delivery", acceptance_type="manual",
            claims_open=True, date_published=datetime.now(timezone.utc).isoformat(),
            date_modified=None, comments_count=0, tags=(),
        )]


class FakeTaskmarket:
    task_id = "0x" + "1" * 64

    def search(self, *, limit):
        return [TaskmarketLead(
            task_id=self.task_id, reference_code="T-1", title="Build a small API",
            description="Build and deliver a small API with tests. " * 8,
            chain_id=8453, mode="bounty", status="open", phase="open",
            reward_base_units="2000000", reward_usdc="2.000000",
            net_reward_usdc="1.800000", escrow_tx_hash="0x" + "2" * 64,
            escrow_tracked=True, escrow_booked_base_units="2000000",
            submission_count=1, award_count=0, expiry_time=None,
            submission_window_open=True, stake_required=False, stake_bps=0,
            platform_fee_bps=1000, tags=(), requester_actor_type="human",
        )]

    def get_task(self, task_id):
        return {
            "id": task_id, "chainId": 8453, "mode": "bounty", "status": "open",
            "description": "Build and deliver a small API with tests. " * 8,
            "reward": "2000000", "netReward": "1800000",
            "escrowTxHash": "0x" + "2" * 64,
            "escrow": {"tracked": True, "booked": "2000000"},
            "submissionCount": 1, "submissionWindowOpen": True,
            "stakeRequired": False, "stakeBps": 0,
        }


class FakeEscrowVerifier:
    def verify_lead(self, lead):
        values = lead.to_dict()
        values["escrow_verified_onchain"] = True
        values["escrow_verification_status"] = "verified"
        values["escrow_verified_amount_base_units"] = values["reward_base_units"]
        return TaskmarketLead(**values)


def test_revenue_engine_federates_sources_and_only_readies_verified_taskmarket():
    with TemporaryDirectory() as directory:
        store = RevenueOpportunityStore(Path(directory) / "revenue.sqlite3")
        engine = RevenueEngine(
            store, basedagents=FakeBasedAgents(), jobbi=FakeJobbi(),
            taskmarket=FakeTaskmarket(), escrow_verifier=FakeEscrowVerifier(),
        )
        result = engine.scan_once(limit=10, verify_limit=10)
        assert result["candidates_saved"] == 3
        assert result["ready_for_owner_review"] == 1
        assert result["external_claims"] == 0
        assert result["submissions"] == 0
        assert result["payments"] == 0
        assert result["revenue_usdc"] == "0.00"
        candidates = {row["source"]: row for row in store.list(limit=10)}
        assert candidates["taskmarket"]["escrow_verified"] is True
        assert candidates["taskmarket"]["net_reward"] == "1.800000"
        assert candidates["taskmarket"]["claim_allowed"] is False
        assert candidates["basedagents"]["status"] == "needs_owner_review"
        assert "independent_escrow_verification_unavailable" in candidates["basedagents"]["reasons"]
        assert candidates["jobbi"]["status"] == "needs_owner_review"
        assert "original_board_terms_and_escrow_need_independent_review" in candidates["jobbi"]["reasons"]


def test_revenue_engine_keeps_other_sources_when_one_source_fails():
    class BrokenBasedAgents:
        def search(self, *, limit):
            raise RuntimeError("offline")

    with TemporaryDirectory() as directory:
        store = RevenueOpportunityStore(Path(directory) / "revenue.sqlite3")
        engine = RevenueEngine(
            store, basedagents=BrokenBasedAgents(), jobbi=FakeJobbi(),
            taskmarket=FakeTaskmarket(), escrow_verifier=FakeEscrowVerifier(),
        )
        result = engine.scan_once(limit=10, verify_limit=10)
        assert result["candidates_saved"] == 2
        assert result["source_errors"] == [{"source": "basedagents", "error": "RuntimeError"}]


def test_store_is_idempotent_and_ready_filter_is_explicit():
    with TemporaryDirectory() as directory:
        store = RevenueOpportunityStore(Path(directory) / "revenue.sqlite3")
        engine = RevenueEngine(
            store, basedagents=FakeBasedAgents(), jobbi=FakeJobbi(),
            taskmarket=FakeTaskmarket(), escrow_verifier=FakeEscrowVerifier(),
        )
        engine.scan_once(limit=10, verify_limit=10)
        engine.scan_once(limit=10, verify_limit=10)
        assert len(store.list(limit=10)) == 3
        ready = store.list(limit=10, ready_only=True)
        assert len(ready) == 1
        assert ready[0]["source"] == "taskmarket"


def test_sync_opportunities_posts_bounded_shortlist_and_requires_safe_cloud_ack(tmp_path):
    import json
    from economy.revenue_engine import sync_opportunities

    store = RevenueOpportunityStore(tmp_path / "revenue.sqlite3")
    engine = RevenueEngine(
        store, basedagents=FakeBasedAgents(), jobbi=FakeJobbi(),
        taskmarket=FakeTaskmarket(), escrow_verifier=FakeEscrowVerifier(),
    )
    engine.scan_once(limit=10, verify_limit=10)
    calls = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, limit=-1):
            return json.dumps({
                "imported": 3,
                "enforced": {
                    "review_status": "needs_owner_review",
                    "independent_escrow_verified": False,
                    "payment_verified": False,
                    "claim_allowed": False,
                },
            }).encode()

    def opener(request, timeout):
        calls.append((request, timeout))
        return Response()

    result = sync_opportunities(
        store, worker_url="https://aae.example.workers.dev", token="secret",
        limit=25, opener=opener,
    )
    assert result == {"imported": 3, "status": "synced_owner_review_only"}
    request, timeout = calls[0]
    payload = json.loads(request.data)
    assert len(payload["opportunities"]) == 3
    assert request.full_url == "https://aae.example.workers.dev/v1/owner/revenue-opportunities/import"
    assert request.get_header("Authorization") == "Bearer secret"
    assert timeout == 20
    assert "claim_allowed" not in payload["opportunities"][0]


def test_sync_opportunities_fails_closed_on_invalid_origin_or_cloud_ack(tmp_path):
    import json
    from economy.revenue_engine import sync_opportunities

    store = RevenueOpportunityStore(tmp_path / "revenue.sqlite3")
    engine = RevenueEngine(
        store, basedagents=FakeBasedAgents(), jobbi=FakeJobbi(),
        taskmarket=FakeTaskmarket(), escrow_verifier=FakeEscrowVerifier(),
    )
    engine.scan_once(limit=10, verify_limit=10)
    calls = []
    with pytest.raises(ValueError, match="HTTPS"):
        sync_opportunities(
            store, worker_url="http://unsafe.example", token="secret",
            opener=lambda *args, **kwargs: calls.append(1),
        )
    with pytest.raises(ValueError, match="AAE_QUEUE_TOKEN"):
        sync_opportunities(
            store, worker_url="https://aae.example", token="",
            opener=lambda *args, **kwargs: calls.append(1),
        )

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, limit=-1):
            return json.dumps({
                "imported": 3,
                "enforced": {
                    "review_status": "ready_for_owner_review",
                    "independent_escrow_verified": True,
                    "payment_verified": False,
                    "claim_allowed": False,
                },
            }).encode()

    with pytest.raises(RuntimeError, match="safe owner-review-only"):
        sync_opportunities(
            store, worker_url="https://aae.example", token="secret",
            opener=lambda *args, **kwargs: Response(),
        )
    assert calls == []

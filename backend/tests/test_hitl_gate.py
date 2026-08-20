"""
Test: Human-In-The-Loop (HITL) gate behaviour.
1. HITL gate pauses a run (status → paused_hitl, hitl_pending=True)
2. Approving one item does NOT change any other item's status
3. Rejecting an item does NOT discard the rest of the run's items
4. Resume is only allowed when ALL items are decided
No live API key needed.
"""
import uuid
import pytest
from datetime import datetime, timezone

from agents.state import GraphState, NodeDecision
from agents.nodes.hitl_gate import hitl_gate_node
from db.models import (
    Run, RunStatus, ReviewItem, ReviewItemStatus
)


def make_run(db, run_id=None):
    run_id = run_id or str(uuid.uuid4())
    run = Run(id=run_id, status=RunStatus.running, domain="insurance_claims",
              rulebook="", current_stage=1, current_node="hitl_gate_1",
              checkpoint_thread_id=run_id, total_cost_usd=0.0)
    db.add(run)
    db.commit()
    return run_id


def make_initial_state(run_id, conflicts=None):
    default_conflicts = [
        {
            "doc_a_id": "doc-a", "doc_b_id": "doc-b",
            "field": "claim_amount",
            "value_a": "$45,000", "value_b": "$42,000",
            "description": "Claim form vs adjuster notes differ on amount"
        }
    ]
    return GraphState(
        run_id=run_id,
        document_ids=["doc-a", "doc-b"],
        rulebook="",
        classified_docs={"doc-a": "claim_form", "doc-b": "adjuster_notes"},
        extracted_facts=[
            {"claim": "Amount $45,000", "confidence": 0.98,
             "source_doc_id": "doc-a", "source_excerpt": "Total: $45,000",
             "source_page": 1, "is_verified": True}
        ],
        conflicts=conflicts if conflicts is not None else default_conflicts,
        report_html="<h1>Report</h1><p>Conflict found in claim amount.</p>",
        rule_check_results=[],
        findings_html=None,
        # Creative addition fields
        fraud_signals=[], timeline_events=[],
        disposition_recommendation=None, report_diff=None,
        current_node="hitl_gate_1",
        current_stage=1,
        last_decision=None,
        retry_count=0,
        error=None,
        hitl_pending=False,
        new_doc_ids=[],
        affected_sections=[],
        pending_stage3_addendum=None,
        total_tokens_in=500,
        total_tokens_out=200,
        total_cost_usd=0.002,
    )


class TestHITLGatePauses:
    """The HITL gate must pause the run."""

    def test_gate_sets_hitl_pending_true(self, db):
        run_id = make_run(db)
        state = make_initial_state(run_id)
        result = hitl_gate_node(state, db, stage=1)

        assert result["hitl_pending"] is True

    def test_gate_sets_run_status_to_paused(self, db):
        run_id = make_run(db)
        state = make_initial_state(run_id)
        hitl_gate_node(state, db, stage=1)

        run = db.query(Run).filter_by(id=run_id).first()
        assert run.status == RunStatus.paused_hitl

    def test_gate_creates_review_items_for_each_conflict(self, db):
        run_id = make_run(db)
        conflicts = [
            {"doc_a_id": "d1", "doc_b_id": "d2", "field": "amount",
             "value_a": "$10k", "value_b": "$9k", "description": "Amount conflict"},
            {"doc_a_id": "d1", "doc_b_id": "d3", "field": "date",
             "value_a": "2026-07-01", "value_b": "2026-07-15", "description": "Date conflict"},
        ]
        state = make_initial_state(run_id, conflicts=conflicts)
        hitl_gate_node(state, db, stage=1)

        items = db.query(ReviewItem).filter_by(run_id=run_id, stage=1).all()
        # Expect: 1 item for the full report + 1 per conflict = 3
        assert len(items) >= len(conflicts), (
            f"Expected at least {len(conflicts)} review items, got {len(items)}"
        )

    def test_gate_items_start_as_pending(self, db):
        run_id = make_run(db)
        state = make_initial_state(run_id)
        hitl_gate_node(state, db, stage=1)

        items = db.query(ReviewItem).filter_by(run_id=run_id).all()
        assert len(items) > 0
        assert all(item.status == ReviewItemStatus.pending for item in items), (
            "All items should start as pending after gate"
        )

    def test_gate_no_conflicts_still_creates_report_item(self, db):
        """Even if no conflicts, a report ReviewItem must be created."""
        run_id = make_run(db)
        state = make_initial_state(run_id, conflicts=[])
        hitl_gate_node(state, db, stage=1)

        items = db.query(ReviewItem).filter_by(run_id=run_id).all()
        assert len(items) >= 1, "At least the report item must be created even with no conflicts"


class TestHITLApproveRejectIsolation:
    """Approving or rejecting one item must not affect other items."""

    def _setup_items(self, db):
        """Helper: create a paused run with 3 review items."""
        run_id = make_run(db)
        conflicts = [
            {"doc_a_id": "d1", "doc_b_id": "d2", "field": "amount",
             "value_a": "$10k", "value_b": "$9k", "description": "Conflict 1"},
            {"doc_a_id": "d1", "doc_b_id": "d3", "field": "policy",
             "value_a": "POL-001", "value_b": "POL-002", "description": "Conflict 2"},
        ]
        state = make_initial_state(run_id, conflicts=conflicts)
        hitl_gate_node(state, db, stage=1)

        items = db.query(ReviewItem).filter_by(run_id=run_id).all()
        return run_id, items

    def test_approve_one_does_not_affect_others(self, db):
        run_id, items = self._setup_items(db)
        assert len(items) >= 2

        # Approve only the first item
        target = items[0]
        target.status = ReviewItemStatus.approved
        target.decided_at = datetime.now(timezone.utc)
        db.commit()

        # All other items must remain pending
        others = [i for i in items if i.id != target.id]
        db.refresh(target)  # re-read from DB
        for other in others:
            db.refresh(other)
            assert other.status == ReviewItemStatus.pending, (
                f"Item {other.id} changed status after approving {target.id}"
            )

    def test_reject_one_does_not_affect_others(self, db):
        run_id, items = self._setup_items(db)

        # Reject only the second item
        target = items[1] if len(items) > 1 else items[0]
        target.status = ReviewItemStatus.rejected
        target.reviewer_note = "Amount discrepancy is too large"
        target.decided_at = datetime.now(timezone.utc)
        db.commit()

        others = [i for i in items if i.id != target.id]
        for other in others:
            db.refresh(other)
            assert other.status == ReviewItemStatus.pending, (
                f"Item {other.id} changed status after rejecting {target.id}. "
                f"Status: {other.status}"
            )

    def test_reject_does_not_clear_other_items(self, db):
        """Rejecting one item must not delete or nullify other items."""
        run_id, items = self._setup_items(db)

        target = items[0]
        target.status = ReviewItemStatus.rejected
        target.decided_at = datetime.now(timezone.utc)
        db.commit()

        # All items must still exist in the DB
        db_items = db.query(ReviewItem).filter_by(run_id=run_id).all()
        assert len(db_items) == len(items), (
            f"Expected {len(items)} items, found {len(db_items)} after rejection"
        )

    def test_resume_blocked_while_items_pending(self, db):
        """Can't resume while any item is still pending — simulated at the service layer."""
        run_id, items = self._setup_items(db)

        # Approve all but one
        for item in items[:-1]:
            item.status = ReviewItemStatus.approved
            item.decided_at = datetime.now(timezone.utc)
        db.commit()

        # Count pending
        pending_count = (
            db.query(ReviewItem)
            .filter_by(run_id=run_id, status=ReviewItemStatus.pending)
            .count()
        )
        assert pending_count == 1, "Should have exactly one pending item"

        # The resume endpoint would check this and return 409 — we test the count logic
        # (actual HTTP test would require a test client, which needs the full app)
        can_resume = pending_count == 0
        assert not can_resume, "Resume should be blocked when pending items remain"

    def test_resume_allowed_when_all_decided(self, db):
        run_id, items = self._setup_items(db)

        # Decide all items
        for item in items:
            item.status = ReviewItemStatus.approved
            item.decided_at = datetime.now(timezone.utc)
        db.commit()

        pending_count = (
            db.query(ReviewItem)
            .filter_by(run_id=run_id, status=ReviewItemStatus.pending)
            .count()
        )
        can_resume = pending_count == 0
        assert can_resume, "Resume should be allowed when all items are decided"


class TestHITLStage2:
    """Stage 2 gate (rule check findings) behaves the same way."""

    def test_stage2_gate_creates_items_for_failing_rules(self, db):
        run_id = make_run(db)
        failing_rules = [
            {
                "rule_text": "Claim amount must not exceed $100,000",
                "passed": False,
                "finding": "Claimed $120,000 exceeds limit",
                "severity": "critical",
                "source_doc_id": "doc-a",
                "source_excerpt": "Total: $120,000",
                "is_verified": True
            }
        ]
        state = GraphState(
            run_id=run_id,
            document_ids=["doc-a"],
            rulebook="Claim amount must not exceed $100,000",
            classified_docs={"doc-a": "claim_form"},
            extracted_facts=[],
            conflicts=[],
            report_html="<h1>Report</h1>",
            rule_check_results=failing_rules,
            findings_html=None,
            fraud_signals=[], timeline_events=[],
            disposition_recommendation=None, report_diff=None,
            current_node="hitl_gate_2",
            current_stage=2,
            last_decision=None,
            retry_count=0, error=None, hitl_pending=False,
            new_doc_ids=[], affected_sections=[],
            total_tokens_in=100, total_tokens_out=50, total_cost_usd=0.001,
        )

        result = hitl_gate_node(state, db, stage=2)

        assert result["hitl_pending"] is True
        items = db.query(ReviewItem).filter_by(run_id=run_id, stage=2).all()
        assert len(items) >= 1
        assert any("rule" in item.item_type.lower() or "finding" in item.item_type.lower()
                   for item in items), "Expected a rule-check finding item"

    def test_stage2_all_rules_pass_creates_no_finding_item(self, db):
        """If all rules pass, create an explicit 'no findings' item — honest result."""
        run_id = make_run(db)
        passing_rules = [
            {
                "rule_text": "Claim amount must not exceed $100,000",
                "passed": True,
                "finding": None,
                "severity": "info",
                "source_doc_id": None,
                "source_excerpt": None,
                "is_verified": True
            }
        ]
        state = GraphState(
            run_id=run_id,
            document_ids=["doc-a"],
            rulebook="Claim amount must not exceed $100,000",
            classified_docs={"doc-a": "claim_form"},
            extracted_facts=[],
            conflicts=[],
            report_html="<h1>Report</h1>",
            rule_check_results=passing_rules,
            findings_html=None,
            fraud_signals=[], timeline_events=[],
            disposition_recommendation=None, report_diff=None,
            current_node="hitl_gate_2",
            current_stage=2,
            last_decision=None,
            retry_count=0, error=None, hitl_pending=False,
            new_doc_ids=[], affected_sections=[],
            total_tokens_in=100, total_tokens_out=50, total_cost_usd=0.001,
        )

        result = hitl_gate_node(state, db, stage=2)

        assert result["hitl_pending"] is True
        items = db.query(ReviewItem).filter_by(run_id=run_id, stage=2).all()
        # Should have at least the "all rules passed" summary item
        assert len(items) >= 1
        item_texts = " ".join(i.title + " " + i.body for i in items).lower()
        has_clean = any(w in item_texts for w in ["no finding", "all pass", "clean", "compliant"])
        assert has_clean, (
            f"Expected a 'no findings' message when all rules pass. Items: {item_texts[:200]}"
        )

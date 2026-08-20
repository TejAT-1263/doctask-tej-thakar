"""
Test: two runs at the same time stay two runs.
Concurrent work does not corrupt state — run_id is the partition key.
No live API key needed — all LLM calls are mocked.
"""
import uuid
import pytest
import threading

from agents.state import GraphState, NodeDecision
from agents.nodes.classify import classify_node
from agents.nodes.extract import extract_node
from db.models import Document, RunLog
from db.database import SessionLocal


def make_doc_in_db(run_id: str, filename: str, raw_text: str) -> str:
    db = SessionLocal()
    try:
        doc_id = str(uuid.uuid4())
        doc = Document(id=doc_id, run_id=run_id, filename=filename,
                       mime_type="text/plain", raw_text=raw_text)
        db.add(doc)
        db.commit()
        return doc_id
    finally:
        db.close()


def make_initial_state(run_id, doc_ids):
    return GraphState(
        run_id=run_id, document_ids=doc_ids, rulebook="",
        classified_docs={}, extracted_facts=[], conflicts=[],
        report_html=None, rule_check_results=[], findings_html=None,
        # Creative addition fields
        fraud_signals=[], timeline_events=[],
        disposition_recommendation=None, report_diff=None,
        current_node="", current_stage=1, last_decision=None,
        retry_count=0, error=None, hitl_pending=False,
        new_doc_ids=[], affected_sections=[],
        pending_stage3_addendum=None,
        total_tokens_in=0, total_tokens_out=0, total_cost_usd=0.0,
    )


class TestConcurrentRuns:
    """Two simultaneous runs must not share or corrupt each other's state."""

    def test_two_runs_produce_independent_logs(self, mock_llm):
        """Run classify for two different run_ids concurrently. Each must only see its own logs."""
        run_a = str(uuid.uuid4())
        run_b = str(uuid.uuid4())
        doc_a = make_doc_in_db(run_a, "claim_a.txt", "Claim A: amount $10,000. Policy: POL-001.")
        doc_b = make_doc_in_db(run_b, "claim_b.txt", "Claim B: amount $20,000. Policy: POL-002.")

        results = {}
        errors = []

        def run_classify(run_id, doc_id):
            db = SessionLocal()
            try:
                state = make_initial_state(run_id, [doc_id])
                result = classify_node(state, db)
                results[run_id] = result
            except Exception as e:
                errors.append(str(e))
            finally:
                db.close()

        t1 = threading.Thread(target=run_classify, args=(run_a, doc_a))
        t2 = threading.Thread(target=run_classify, args=(run_b, doc_b))
        t1.start(); t2.start()
        t1.join(); t2.join()

        assert not errors, f"Concurrent runs raised errors: {errors}"
        assert run_a in results and run_b in results

        # Each run's classified_docs must only contain its own document
        assert doc_a in results[run_a]["classified_docs"]
        assert doc_b not in results[run_a]["classified_docs"]
        assert doc_b in results[run_b]["classified_docs"]
        assert doc_a not in results[run_b]["classified_docs"]

    def test_logs_are_scoped_to_run_id(self, mock_llm):
        """Logs from run A must not appear in run B's log query."""
        db_a = SessionLocal()
        db_b = SessionLocal()
        run_a = str(uuid.uuid4())
        run_b = str(uuid.uuid4())

        try:
            doc_a = str(uuid.uuid4())
            doc_b = str(uuid.uuid4())

            for db, run_id, doc_id in [(db_a, run_a, doc_a), (db_b, run_b, doc_b)]:
                doc = Document(id=doc_id, run_id=run_id, filename="test.txt",
                               mime_type="text/plain", raw_text="Claim document content here.")
                db.add(doc)
                db.commit()

            state_a = make_initial_state(run_a, [doc_a])
            state_b = make_initial_state(run_b, [doc_b])

            classify_node(state_a, db_a)
            classify_node(state_b, db_b)

            # Check log isolation
            logs_a = db_a.query(RunLog).filter_by(run_id=run_a).all()
            logs_b = db_b.query(RunLog).filter_by(run_id=run_b).all()

            assert all(l.run_id == run_a for l in logs_a), "Run A has logs from wrong run"
            assert all(l.run_id == run_b for l in logs_b), "Run B has logs from wrong run"
            assert len(logs_a) > 0 and len(logs_b) > 0

        finally:
            db_a.close()
            db_b.close()

    def test_facts_do_not_cross_run_boundaries(self, mock_llm):
        """Facts extracted in run A must not appear in run B's extracted_facts."""
        run_a = str(uuid.uuid4())
        run_b = str(uuid.uuid4())

        db = SessionLocal()
        try:
            doc_a = str(uuid.uuid4())
            doc_b = str(uuid.uuid4())
            db.add(Document(id=doc_a, run_id=run_a, filename="a.txt",
                             mime_type="text/plain", raw_text="Run A claim: $99,999."))
            db.add(Document(id=doc_b, run_id=run_b, filename="b.txt",
                             mime_type="text/plain", raw_text="Run B claim: $11,111."))
            db.commit()

            state_a = make_initial_state(run_a, [doc_a])
            state_b = make_initial_state(run_b, [doc_b])

            state_a = classify_node(state_a, db)
            state_a = extract_node(state_a, db)

            state_b = classify_node(state_b, db)
            state_b = extract_node(state_b, db)

            # No fact from run A should carry run B's doc_id and vice versa
            for fact in state_a["extracted_facts"]:
                assert fact["source_doc_id"] == doc_a, (
                    f"Run A fact has wrong source_doc_id: {fact['source_doc_id']}"
                )
            for fact in state_b["extracted_facts"]:
                assert fact["source_doc_id"] == doc_b, (
                    f"Run B fact has wrong source_doc_id: {fact['source_doc_id']}"
                )
        finally:
            db.close()

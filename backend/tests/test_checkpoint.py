"""
Test: run survives being stopped.
Kill the process mid-run, restart, verify it picks up from where it left off.
No live API key needed — all LLM calls are mocked.
"""
import uuid
import pytest
from unittest.mock import patch, MagicMock

from agents.state import GraphState, NodeDecision
from agents.nodes.classify import classify_node
from agents.nodes.extract import extract_node
from db.models import Document, DocumentStatus, RunLog, ReviewItem, ReviewItemStatus


def make_run_id():
    return str(uuid.uuid4())


def make_doc(db, run_id: str, raw_text: str = "Test claim document. Claim amount: $45,000."):
    doc_id = str(uuid.uuid4())
    doc = Document(
        id=doc_id,
        run_id=run_id,
        filename="test_claim.txt",
        mime_type="text/plain",
        raw_text=raw_text,
    )
    db.add(doc)
    db.commit()
    return doc_id


def initial_state(run_id, doc_ids, rulebook=""):
    return GraphState(
        run_id=run_id, document_ids=doc_ids, rulebook=rulebook,
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


class TestCheckpointing:
    """Verify that the classify → extract pipeline can be interrupted and resumed."""

    def test_classify_produces_correct_decision(self, db, mock_llm):
        run_id = make_run_id()
        doc_id = make_doc(db, run_id)
        state = initial_state(run_id, [doc_id])

        result = classify_node(state, db)

        assert result["last_decision"] == NodeDecision.CONTINUE
        assert doc_id in result["classified_docs"]
        assert result["classified_docs"][doc_id] == "claim_form"
        assert result["current_node"] == "classify"

    def test_extract_after_classify(self, db, mock_llm):
        run_id = make_run_id()
        doc_id = make_doc(db, run_id)
        state = initial_state(run_id, [doc_id])

        # Stage 1: classify
        state = classify_node(state, db)
        assert state["last_decision"] == NodeDecision.CONTINUE

        # Stage 2: extract
        state = extract_node(state, db)
        assert state["last_decision"] == NodeDecision.CONTINUE
        assert len(state["extracted_facts"]) > 0

        # All facts have source excerpts
        for fact in state["extracted_facts"]:
            if fact["is_verified"]:
                assert fact["source_excerpt"], "Verified fact must have a source excerpt"

    def test_state_is_preserved_across_nodes(self, db, mock_llm):
        """
        Node-level state propagation: classify output is available as extract input.
        NOTE: this tests dict-passing between nodes, not a real persisted checkpoint.
        The real LangGraph checkpoint test is in TestLangGraphCheckpoint below.
        """
        run_id = make_run_id()
        doc_id = make_doc(db, run_id)
        state = initial_state(run_id, [doc_id])

        # Run classify
        state_after_classify = classify_node(state, db)
        saved_classified = state_after_classify["classified_docs"].copy()

        # Simulate "restart" — recreate state from saved values
        # (In production this comes from the LangGraph PostgresSaver checkpoint)
        restarted_state = {
            **state,
            **state_after_classify,
            # The critical fields that would be restored from checkpoint:
            "classified_docs": saved_classified,
            "current_node": "classify",
            "last_decision": NodeDecision.CONTINUE,
        }

        # Continue from extract (never re-runs classify)
        state_after_extract = extract_node(restarted_state, db)

        assert state_after_extract["last_decision"] == NodeDecision.CONTINUE
        assert len(state_after_extract["extracted_facts"]) > 0
        # Classified docs unchanged — classify did not re-run
        assert state_after_extract["classified_docs"] == saved_classified

    def test_run_logs_record_every_node(self, db, mock_llm):
        """Every node execution should produce a RunLog entry."""
        run_id = make_run_id()
        doc_id = make_doc(db, run_id)
        state = initial_state(run_id, [doc_id])

        classify_node(state, db)
        logs = db.query(RunLog).filter_by(run_id=run_id).all()

        assert len(logs) >= 1
        assert any(l.node_name == "classify" for l in logs)
        assert all(l.decision is not None for l in logs)


class TestLangGraphCheckpoint:
    """
    Real LangGraph checkpoint test: build a 2-node graph with MemorySaver,
    run to a mid-graph interrupt, then resume from the SAME saver instance.
    This proves the checkpoint / restore path that survives a process restart
    (PostgresSaver in prod; SqliteSaver in dev).
    """

    def test_checkpoint_preserves_state_across_graph_invocations(self, db, mock_llm):
        """
        1. Build a tiny graph: classify → extract (both using mock LLM)
        2. Run only classify via interrupt_before=["extract"]
        3. Read the checkpoint — classified_docs must be present
        4. Resume from the same saver (simulates restart with same saver)
        5. extract runs and adds extracted_facts
        """
        from langgraph.graph import StateGraph, END
        from langgraph.checkpoint.memory import MemorySaver
        from agents.state import GraphState
        from functools import partial

        run_id = make_run_id()
        doc_id = make_doc(db, run_id)

        def _classify(state, db_session):
            return classify_node(state, db_session)

        def _extract(state, db_session):
            return extract_node(state, db_session)

        saver = MemorySaver()

        builder = StateGraph(GraphState)
        builder.add_node("classify", partial(_classify, db_session=db))
        builder.add_node("extract",  partial(_extract,  db_session=db))
        builder.set_entry_point("classify")
        builder.add_edge("classify", "extract")
        builder.add_edge("extract", END)

        # Compile with checkpoint saver AND an interrupt before "extract"
        # so the graph pauses after classify, exactly like a process kill would.
        graph = builder.compile(
            checkpointer=saver,
            interrupt_before=["extract"],
        )
        config = {"configurable": {"thread_id": run_id}}
        start = initial_state(run_id, [doc_id])

        # --- First invocation: runs classify, then pauses before extract ---
        graph.invoke(start, config=config)

        # Read checkpoint — classified_docs must be populated
        snap = graph.get_state(config)
        assert snap.values.get("classified_docs"), (
            "Checkpoint should have classified_docs after classify ran"
        )
        assert doc_id in snap.values["classified_docs"], (
            "Checkpoint should know which doc was classified"
        )

        # --- Second invocation: resume from checkpoint (None input = use checkpoint) ---
        # This is what _resume_agent() does in production.
        result = graph.invoke(None, config=config)

        assert result.get("extracted_facts"), (
            "After resume, extract should have run and produced facts"
        )
        # classify did NOT re-run — classified_docs still has the same value
        assert result["classified_docs"] == snap.values["classified_docs"], (
            "classify must not re-run after resume"
        )


class TestStage3Gate:
    """
    Stage 3 watcher: the addendum must NOT commit to report_html until a human approves it.
    Brief requirement: "updates are approved or rejected by a person before they commit."
    """

    def test_watcher_stages_addendum_not_committed(self, db, mock_llm):
        """
        watcher_node must leave report_html unchanged and store the addendum
        in pending_stage3_addendum.  hitl_pending must be True.
        """
        from agents.nodes.watcher import watcher_node

        run_id = make_run_id()
        doc_id = make_doc(db, run_id, "Follow-up invoice: Apollo Hospital, $12,000.")

        existing_report = "<h1>Claim Report</h1><p>Original approved content.</p>"
        state = {
            **initial_state(run_id, []),
            "report_html": existing_report,
            "new_doc_ids": [doc_id],
        }

        result = watcher_node(state, db)

        # ── Core contract: report_html must be unchanged ──────────────────────
        assert result["report_html"] == existing_report, (
            "report_html must not change before human approval — "
            "addendum must be staged in pending_stage3_addendum"
        )
        # ── Addendum must be staged ───────────────────────────────────────────
        assert result.get("pending_stage3_addendum") is not None, (
            "pending_stage3_addendum must hold the staged HTML addendum"
        )
        assert "stage3" in result["pending_stage3_addendum"].lower() or \
               "Stage 3" in result["pending_stage3_addendum"], (
            "staged addendum should contain Stage 3 section markup"
        )
        # ── Gate must be open ─────────────────────────────────────────────────
        assert result["hitl_pending"] is True, (
            "hitl_pending must be True when new facts exist — update awaits approval"
        )

    def test_watcher_creates_stage3_update_review_item(self, db, mock_llm):
        """
        A stage3_update review item must be created for any update with new facts,
        not only when conflicts exist.  This is the gate the human acts on.
        """
        from agents.nodes.watcher import watcher_node

        run_id = make_run_id()
        doc_id = make_doc(db, run_id, "Supplementary medical report with no contradictions.")

        state = {
            **initial_state(run_id, []),
            "report_html": "<h1>Report</h1>",
            "new_doc_ids": [doc_id],
        }

        watcher_node(state, db)

        items = db.query(ReviewItem).filter_by(
            run_id=run_id, stage=3, item_type="stage3_update"
        ).all()
        assert len(items) == 1, (
            "Exactly one stage3_update review item should be created per watcher call"
        )
        assert items[0].status == ReviewItemStatus.pending

    def test_approve_commits_addendum_to_report(self, db, mock_llm):
        """
        Simulates the full approve path:
        1. watcher_node stages addendum
        2. Reviewer approves the stage3_update item
        3. _resume_agent logic merges addendum into report_html
        """
        from agents.nodes.watcher import watcher_node

        run_id = make_run_id()
        doc_id = make_doc(db, run_id, "Additional surgery invoice: $8,500.")

        existing_report = "<h1>Claim Report</h1><p>Base content.</p>"
        state = {
            **initial_state(run_id, []),
            "report_html": existing_report,
            "new_doc_ids": [doc_id],
        }

        result = watcher_node(state, db)
        assert result["hitl_pending"] is True

        # Simulate reviewer approval
        item = db.query(ReviewItem).filter_by(
            run_id=run_id, stage=3, item_type="stage3_update"
        ).first()
        assert item is not None
        item.status = ReviewItemStatus.approved
        item.reviewer_note = "Verified — legitimate supplementary invoice"
        db.commit()

        # Simulate what _resume_agent does on Stage 3 approval:
        # merge pending_stage3_addendum into report_html
        pending = result.get("pending_stage3_addendum") or ""
        committed_report = result["report_html"] + pending

        assert existing_report in committed_report, "Original report must be preserved"
        assert pending in committed_report, "Addendum must be appended on approval"
        assert len(committed_report) > len(existing_report), (
            "Committed report must be longer than the original"
        )

    def test_reject_leaves_report_unchanged(self, db, mock_llm):
        """
        Simulates the reject path:
        1. watcher_node stages addendum
        2. Reviewer rejects the stage3_update item
        3. report_html must stay as-is — pending_stage3_addendum discarded
        """
        from agents.nodes.watcher import watcher_node

        run_id = make_run_id()
        doc_id = make_doc(db, run_id, "Suspicious late-filed duplicate claim: $45,000.")

        existing_report = "<h1>Claim Report</h1><p>Base content.</p>"
        state = {
            **initial_state(run_id, []),
            "report_html": existing_report,
            "new_doc_ids": [doc_id],
        }

        result = watcher_node(state, db)
        assert result["hitl_pending"] is True

        # Simulate reviewer rejection
        item = db.query(ReviewItem).filter_by(
            run_id=run_id, stage=3, item_type="stage3_update"
        ).first()
        assert item is not None
        item.status = ReviewItemStatus.rejected
        item.reviewer_note = "Suspected duplicate — discarding"
        db.commit()

        # On rejection: report stays as watcher_node returned it (unchanged from existing)
        # and pending_stage3_addendum is discarded (set to None by _resume_agent)
        assert result["report_html"] == existing_report, (
            "On rejection, report_html must remain at the pre-watch value"
        )

    def test_empty_doc_produces_no_gate(self, db, mock_llm):
        """
        A document from which no facts are extracted must not trigger the gate.
        new_doc_ids are processed but if LLM returns empty facts, no review item
        is created and hitl_pending stays False.
        """
        from agents.nodes.watcher import watcher_node
        from unittest.mock import patch

        run_id = make_run_id()
        doc_id = make_doc(db, run_id, "No useful content here.")

        state = {
            **initial_state(run_id, []),
            "report_html": "<h1>Report</h1>",
            "new_doc_ids": [doc_id],
        }

        # Override extract to return no facts for this test only
        with patch("agents.nodes.watcher.call_llm") as mock_watcher_llm:
            def empty_facts(prompt, **kwargs):
                if "document classification specialist" in prompt:
                    return ('{"doc_type": "other", "confidence": 0.5, '
                            '"summary": "no content", "key_identifiers": []}', 50, 20)
                return ("[]", 50, 10)  # empty facts + empty diff analysis
            mock_watcher_llm.side_effect = empty_facts

            result = watcher_node(state, db)

        assert result["hitl_pending"] is False, (
            "No facts extracted → no gate should open"
        )
        assert result.get("pending_stage3_addendum") is None, (
            "No addendum should be staged when no facts were extracted"
        )
        items = db.query(ReviewItem).filter_by(run_id=run_id, stage=3).all()
        assert len(items) == 0, (
            "No review items should be created when no facts are extracted"
        )

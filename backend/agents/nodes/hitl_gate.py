"""
HITLGateNode — pauses the graph and writes ReviewItems to DB.
The graph DOES NOT resume until all items in this stage have a decision.
Approving one item does NOT affect others.
Rejecting one does NOT discard the rest.
"""
from datetime import datetime
from sqlalchemy.orm import Session

from agents.state import GraphState, NodeDecision
from agents.nodes.base import log_node
from db.models import Run, RunStatus, ReviewItem


def hitl_gate_node(state: GraphState, db: Session, stage: int) -> GraphState:
    """
    Write pending review items for `stage` and pause the run.
    Called after Stage 1 (stage=1) and after Stage 2 (stage=2).
    """
    run_id = state["run_id"]

    # Build review items based on stage
    if stage == 1:
        items = _build_stage1_items(state)
    else:
        items = _build_stage2_items(state)

    # Write items to DB
    for item_data in items:
        item = ReviewItem(
            run_id=run_id,
            stage=stage,
            **item_data,
        )
        db.add(item)

    # Mark run as paused
    run: Run = db.query(Run).filter_by(id=run_id).first()
    if run:
        run.status = RunStatus.paused_hitl
        run.current_node = f"hitl_gate_stage{stage}"
        run.current_stage = stage

    db.commit()

    log_node(
        db, run_id, f"hitl_gate_stage{stage}", stage=stage,
        decision=NodeDecision.ESCALATE,   # "escalate to human" is the right label
        output_summary=f"created {len(items)} review items — run paused",
    )

    return {
        **state,
        "hitl_pending": True,
        "current_node": f"hitl_gate_stage{stage}",
        "current_stage": stage,
        "last_decision": NodeDecision.ESCALATE,
    }


def _build_stage1_items(state: GraphState) -> list[dict]:
    """Report sections and conflicts waiting for Stage 1 review."""
    items = []

    # One item for the full report
    if state.get("report_html"):
        items.append({
            "item_type": "report_section",
            "title": "Stage 1 Analysis Report",
            "body": state["report_html"],
            "source_ref": None,
        })

    # One item per conflict
    for i, conflict in enumerate(state.get("conflicts", [])):
        items.append({
            "item_type": "conflict",
            "title": f"Conflict #{i+1}: {conflict['field']}",
            "body": (
                f"Document A ({conflict['doc_a_id']}): {conflict['value_a']}\n"
                f"Document B ({conflict['doc_b_id']}): {conflict['value_b']}\n\n"
                f"{conflict['description']}"
            ),
            "source_ref": conflict["doc_a_id"],
        })

    return items


def _build_stage2_items(state: GraphState) -> list[dict]:
    """Rule-check findings waiting for Stage 2 review."""
    items = []

    for result in state.get("rule_check_results", []):
        if not result.get("passed"):
            severity = result.get("severity", "info").upper()
            items.append({
                "item_type": "finding",
                "title": f"[{severity}] Rule: {result['rule_text'][:80]}",
                "body": (
                    f"Finding: {result.get('finding', 'No details')}\n\n"
                    f"Source: {result.get('source_excerpt', 'Not verified')}\n"
                    f"Verified: {result.get('is_verified', False)}"
                ),
                "source_ref": result.get("source_doc_id"),
            })

    # If everything passed — add an explicit "no findings" item
    if not items:
        items.append({
            "item_type": "finding",
            "title": "Rule Check Complete — No Findings",
            "body": "No findings: all rules in the provided checklist passed and the document set is compliant.",
            "source_ref": None,
        })

    return items

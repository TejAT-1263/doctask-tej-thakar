"""
RecommendNode — Stage 2, after hitl_gate_2.

Generates a structured claim disposition recommendation:
  APPROVE | DENY | REQUEST_MORE_INFO

This is decision SUPPORT for the human adjuster — not a final decision.
The recommendation is grounded in:
  - Extracted facts and their verifiability
  - Conflicts detected (with taxonomy and severity)
  - Rule check results (passed/failed, severity)
  - Fraud signals detected by the pattern-based node
  - HITL decisions (what the human reviewer approved/rejected)

Design principles:
  - Conservative: prefer REQUEST_MORE_INFO over DENY unless evidence is unambiguous
  - DENY only when a coverage exclusion or hard policy rule is clearly violated
  - Every claim in the rationale must be supported by the data in state
  - India-aware: references IRDAI where relevant
"""
import time
import json
from sqlalchemy.orm import Session

from agents.state import GraphState, NodeDecision, DispositionRecommendation
from agents.prompts import DISPOSITION_PROMPT
from agents.nodes.base import log_node, parse_json_safe
from db.models import ReviewItem, ReviewItemStatus
from services.llm_client import call_llm


def recommend_node(state: GraphState, db: Session) -> GraphState:
    """Generate a structured disposition recommendation and store it in state."""
    run_id = state["run_id"]

    facts           = state.get("extracted_facts", [])
    conflicts       = state.get("conflicts", [])
    rule_results    = state.get("rule_check_results", [])
    fraud_signals   = state.get("fraud_signals", [])

    # Retrieve HITL decisions from DB for context
    hitl_decisions = _get_hitl_decisions(run_id, db)

    t0 = time.monotonic()

    # Build compact summaries for the prompt (avoid token explosion)
    facts_summary = _summarise_facts(facts)
    conflicts_summary = _summarise_conflicts(conflicts)
    rule_summary = _summarise_rules(rule_results)
    signals_summary = _summarise_signals(fraud_signals)

    prompt = DISPOSITION_PROMPT.format(
        facts_json=json.dumps(facts_summary, indent=2)[:4000],
        conflicts_json=json.dumps(conflicts_summary, indent=2),
        rule_check_json=json.dumps(rule_summary, indent=2)[:3000],
        signals_json=json.dumps(signals_summary, indent=2),
        hitl_decisions_json=json.dumps(hitl_decisions, indent=2)[:2000],
    )

    try:
        result_text, tok_in, tok_out = call_llm(prompt)
        rec_raw = parse_json_safe(result_text)

        # Guard: parse_json_safe may extract a list if LLM prose contains []
        if not isinstance(rec_raw, dict):
            raise ValueError(
                f"Expected JSON object from disposition LLM, got {type(rec_raw).__name__}. "
                f"Raw: {result_text[:120]}"
            )

        # Validate and sanitise
        disposition = str(rec_raw.get("disposition", "REQUEST_MORE_INFO")).upper()
        if disposition not in ("APPROVE", "DENY", "REQUEST_MORE_INFO"):
            disposition = "REQUEST_MORE_INFO"

        confidence = str(rec_raw.get("confidence", "LOW")).upper()
        if confidence not in ("HIGH", "MEDIUM", "LOW"):
            confidence = "LOW"

        recommendation = DispositionRecommendation(
            disposition=disposition,
            confidence=confidence,
            rationale=str(rec_raw.get("rationale", "")),
            supporting_findings=[
                str(f) for f in rec_raw.get("supporting_findings", [])
            ],
            blocking_issues=[
                str(i) for i in rec_raw.get("blocking_issues", [])
            ],
        )

        duration = int((time.monotonic() - t0) * 1000)
        log_node(
            db, run_id, "recommend", stage=2,
            decision=NodeDecision.CONTINUE,
            output_summary=(
                f"disposition={disposition} confidence={confidence} "
                f"supporting={len(recommendation['supporting_findings'])} "
                f"blocking={len(recommendation['blocking_issues'])}"
            ),
            duration_ms=duration,
            tokens_in=tok_in, tokens_out=tok_out,
        )

        return {
            **state,
            "disposition_recommendation": recommendation,
            "current_node": "recommend",
            "last_decision": NodeDecision.CONTINUE,
        }

    except Exception as e:
        log_node(db, run_id, "recommend", stage=2,
                 decision=NodeDecision.SKIP, error_detail=str(e))
        # Gracefully degrade — pipeline continues without recommendation
        return {
            **state,
            "disposition_recommendation": None,
            "current_node": "recommend",
            "last_decision": NodeDecision.SKIP,
        }


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _get_hitl_decisions(run_id: str, db: Session) -> list[dict]:
    """Retrieve all HITL decisions made for this run."""
    items = db.query(ReviewItem).filter_by(run_id=run_id).all()
    return [
        {
            "title": item.title,
            "stage": item.stage,
            "type": item.item_type,
            "status": item.status,
            "reviewer_note": item.reviewer_note or "",
        }
        for item in items
        if item.status != ReviewItemStatus.pending
    ]


def _summarise_facts(facts: list) -> list[dict]:
    """Compact fact summary: claim + confidence + is_verified only."""
    return [
        {
            "claim": f.get("claim", ""),
            "confidence": f.get("confidence", 0),
            "is_verified": f.get("is_verified", True),
        }
        for f in facts[:30]  # cap at 30 facts to control prompt size
    ]


def _summarise_conflicts(conflicts: list) -> list[dict]:
    """Compact conflict summary with taxonomy."""
    return [
        {
            "field": c.get("field", ""),
            "description": c.get("description", ""),
            "conflict_type": c.get("conflict_type", "FACTUAL"),
            "severity": c.get("severity", "medium"),
        }
        for c in conflicts
    ]


def _summarise_rules(rule_results: list) -> list[dict]:
    """Compact rule check summary: only the relevant fields."""
    return [
        {
            "rule": r.get("rule_text", ""),
            "passed": r.get("passed", True),
            "finding": r.get("finding"),
            "severity": r.get("severity", "info"),
            "is_verified": r.get("is_verified", True),
        }
        for r in rule_results
    ]


def _summarise_signals(signals: list) -> list[dict]:
    """Compact fraud signal summary."""
    return [
        {
            "signal_id": s.get("signal_id", ""),
            "title": s.get("title", ""),
            "confidence": s.get("confidence", "LOW"),
            "description": s.get("description", ""),
        }
        for s in signals
    ]

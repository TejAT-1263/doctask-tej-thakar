"""
ReconcileNode — Stage 1, step 4 (after fraud_signal).

Two responsibilities:
  1. Conflict detection — finds contradictions between documents, now with taxonomy
     (FACTUAL | TEMPORAL | DEFINITIONAL | OMISSION) and severity (low/medium/high).
  2. Timeline reconstruction — extracts all dated events from facts and surfaces
     temporal paradoxes.

Conflicts are surfaced with their type and severity; they are never silently resolved.
The final report is generated here, incorporating conflicts, timeline, and fraud signals.
"""
import time
import json
from sqlalchemy.orm import Session

from agents.state import GraphState, NodeDecision, Conflict, TimelineEvent
from agents.prompts import (
    RECONCILE_PROMPT,
    INTRA_DOC_RECONCILE_PROMPT,
    TIMELINE_EXTRACTION_PROMPT,
    REPORT_GENERATION_PROMPT,
)
from agents.nodes.base import log_node, parse_json_safe
from db.models import Document
from services.llm_client import call_llm


def reconcile_node(state: GraphState, db: Session) -> GraphState:
    run_id = state["run_id"]
    facts = state.get("extracted_facts", [])
    classified = state.get("classified_docs", {})

    if not facts:
        log_node(db, run_id, "reconcile", stage=1,
                 decision=NodeDecision.SKIP,
                 output_summary="No facts to reconcile — skipping")
        return {
            **state,
            "conflicts": [],
            "timeline_events": [],
            "current_node": "reconcile",
            "last_decision": NodeDecision.SKIP,
        }

    t0 = time.monotonic()

    # Build doc types map for context
    doc_types = {doc_id: classified.get(doc_id, "unknown") for doc_id in classified}

    # ── Step 1: Conflict detection with taxonomy ──────────────────────────────
    # Cross-document conflicts require at least 2 distinct source documents.
    # Skip the LLM call entirely for single-document runs — it's both correct
    # (no cross-doc conflicts possible) and avoids the model returning prose
    # instead of [] when it "sees" only one source.
    unique_doc_ids = list({
        f.get("source_doc_id", "")
        for f in facts
        if f.get("source_doc_id")
    })

    conflicts: list[Conflict] = []

    if len(unique_doc_ids) < 2:
        # Single-document run: run an intra-document consistency check instead.
        # Cross-document reconciliation is impossible, but a single doc can still
        # have internal contradictions (e.g. treatment date before incident date,
        # totals that don't add up, conflicting section values).
        intra_prompt = INTRA_DOC_RECONCILE_PROMPT.format(
            facts_json=json.dumps(facts, indent=2)[:8000],
        )
        result_text = ""
        tok_in = tok_out = 0
        try:
            result_text, tok_in, tok_out = call_llm(intra_prompt)
            conflicts_raw = parse_json_safe(result_text)

            if not isinstance(conflicts_raw, list):
                conflicts_raw = []

            for c in conflicts_raw:
                ct = str(c.get("conflict_type", "FACTUAL")).upper()
                if ct not in ("FACTUAL", "TEMPORAL", "DEFINITIONAL", "OMISSION"):
                    ct = "FACTUAL"
                sev = str(c.get("severity", "medium")).lower()
                if sev not in ("low", "medium", "high"):
                    sev = "medium"
                conflicts.append(Conflict(
                    doc_a_id=c.get("doc_a_id", unique_doc_ids[0] if unique_doc_ids else ""),
                    doc_b_id=c.get("doc_b_id", unique_doc_ids[0] if unique_doc_ids else ""),
                    field=c.get("field", ""),
                    value_a=c.get("value_a", ""),
                    value_b=c.get("value_b", ""),
                    description=c.get("description", ""),
                    conflict_type=ct,
                    severity=sev,
                ))

            duration_conflicts = int((time.monotonic() - t0) * 1000)
            log_node(
                db, run_id, "reconcile", stage=1,
                decision=NodeDecision.CONTINUE,
                output_summary=(
                    f"Single document — intra-doc consistency check: "
                    f"{len(conflicts)} internal inconsistencies found"
                ),
                duration_ms=duration_conflicts,
                tokens_in=tok_in, tokens_out=tok_out,
            )

        except ValueError:
            # JSON parse failure — default to no conflicts, never block
            duration_conflicts = int((time.monotonic() - t0) * 1000)
            log_node(
                db, run_id, "reconcile", stage=1,
                decision=NodeDecision.CONTINUE,
                output_summary="Intra-doc check: LLM returned prose — defaulting to no conflicts",
                duration_ms=duration_conflicts,
                tokens_in=tok_in, tokens_out=tok_out,
            )
        except Exception as e:
            log_node(db, run_id, "reconcile", stage=1,
                     decision=NodeDecision.CONTINUE,
                     error_detail=str(e),
                     output_summary="Intra-doc check failed — continuing without conflicts")
    else:
        conflict_prompt = RECONCILE_PROMPT.format(
            facts_json=json.dumps(facts, indent=2)[:8000],
            doc_types_json=json.dumps(doc_types, indent=2),
        )

        result_text = ""
        tok_in = tok_out = 0
        try:
            result_text, tok_in, tok_out = call_llm(conflict_prompt)
            conflicts_raw = parse_json_safe(result_text)

            if not isinstance(conflicts_raw, list):
                conflicts_raw = []

            for c in conflicts_raw:
                # Validate conflict_type — default to FACTUAL if unexpected value
                ct = str(c.get("conflict_type", "FACTUAL")).upper()
                if ct not in ("FACTUAL", "TEMPORAL", "DEFINITIONAL", "OMISSION"):
                    ct = "FACTUAL"

                sev = str(c.get("severity", "medium")).lower()
                if sev not in ("low", "medium", "high"):
                    sev = "medium"

                conflicts.append(Conflict(
                    doc_a_id=c.get("doc_a_id", ""),
                    doc_b_id=c.get("doc_b_id", ""),
                    field=c.get("field", ""),
                    value_a=c.get("value_a", ""),
                    value_b=c.get("value_b", ""),
                    description=c.get("description", ""),
                    conflict_type=ct,
                    severity=sev,
                ))

            duration_conflicts = int((time.monotonic() - t0) * 1000)
            log_node(
                db, run_id, "reconcile", stage=1,
                decision=NodeDecision.CONTINUE,
                output_summary=(
                    f"{len(conflicts)} conflicts "
                    f"(FACTUAL={sum(1 for c in conflicts if c['conflict_type']=='FACTUAL')}, "
                    f"TEMPORAL={sum(1 for c in conflicts if c['conflict_type']=='TEMPORAL')}, "
                    f"DEFINITIONAL={sum(1 for c in conflicts if c['conflict_type']=='DEFINITIONAL')}, "
                    f"OMISSION={sum(1 for c in conflicts if c['conflict_type']=='OMISSION')})"
                ),
                duration_ms=duration_conflicts,
                tokens_in=tok_in, tokens_out=tok_out,
            )

        except ValueError as json_err:
            # LLM returned prose instead of parseable JSON — always safe to treat as
            # no conflicts.  Conflict detection defaults to [] (no conflicts proven);
            # the pipeline continues.  We NEVER escalate from a JSON-parse failure
            # in conflict detection — a false-negative (missed conflict) is far less
            # damaging than a pipeline abort on every single-document run.
            duration_conflicts = int((time.monotonic() - t0) * 1000)
            log_node(
                db, run_id, "reconcile", stage=1,
                decision=NodeDecision.CONTINUE,
                output_summary=(
                    f"LLM returned prose instead of JSON — defaulting to no conflicts. "
                    f"First 120 chars: {result_text[:120]!r}"
                ),
                duration_ms=duration_conflicts,
                tokens_in=tok_in, tokens_out=tok_out,
            )
            # conflicts stays []

        except Exception as e:
            log_node(db, run_id, "reconcile", stage=1,
                     decision=NodeDecision.ESCALATE,
                     error_detail=str(e))
            return {
                **state,
                "conflicts": [],
                "timeline_events": [],
                "current_node": "reconcile",
                "last_decision": NodeDecision.ESCALATE,
                "error": f"Reconcile failed: {e}",
            }

    # ── Step 2: Timeline reconstruction ──────────────────────────────────────
    timeline_events: list[TimelineEvent] = _extract_timeline(
        state, db, facts
    )

    # ── Step 3: Generate grounded report ──────────────────────────────────────
    report_state = _generate_report(state, db, facts, conflicts, classified, timeline_events)

    return {
        **state,
        **report_state,
        "conflicts": conflicts,
        "timeline_events": timeline_events,
        "current_node": "reconcile",
        "last_decision": NodeDecision.CONTINUE,
    }


def _extract_timeline(state: GraphState, db: Session, facts: list) -> list[TimelineEvent]:
    """Extract chronological events from facts and flag temporal paradoxes."""
    run_id = state["run_id"]
    t0 = time.monotonic()

    timeline_prompt = TIMELINE_EXTRACTION_PROMPT.format(
        facts_json=json.dumps(facts, indent=2)[:7000]
    )

    try:
        result_text, tok_in, tok_out = call_llm(timeline_prompt)
        raw_events = parse_json_safe(result_text)

        if not isinstance(raw_events, list):
            raw_events = []

        events: list[TimelineEvent] = []
        for e in raw_events:
            events.append(TimelineEvent(
                date_iso=e.get("date_iso"),
                date_raw=str(e.get("date_raw", "")),
                event=str(e.get("event", "")),
                source_doc_id=str(e.get("source_doc_id", "")),
                source_excerpt=str(e.get("source_excerpt", "")),
                is_paradox=bool(e.get("is_paradox", False)),
                paradox_note=e.get("paradox_note"),
            ))

        # Sort: dated events first (chronological), undated last
        def sort_key(ev):
            if ev["date_iso"]:
                return (0, ev["date_iso"])
            return (1, ev["date_raw"])

        events.sort(key=sort_key)

        paradox_count = sum(1 for e in events if e["is_paradox"])
        duration = int((time.monotonic() - t0) * 1000)
        log_node(
            db, run_id, "timeline_extraction", stage=1,
            decision=NodeDecision.CONTINUE,
            output_summary=(
                f"{len(events)} events extracted, "
                f"{paradox_count} temporal paradox(es) detected"
            ),
            duration_ms=duration,
            tokens_in=tok_in, tokens_out=tok_out,
        )
        return events

    except Exception as e:
        log_node(db, run_id, "timeline_extraction", stage=1,
                 decision=NodeDecision.SKIP, error_detail=str(e))
        return []


def _generate_report(
    state: GraphState, db: Session,
    facts: list, conflicts: list[Conflict],
    classified: dict, timeline_events: list[TimelineEvent],
) -> dict:
    """Generate the grounded Stage 1 report via LLM."""
    run_id = state["run_id"]
    t0 = time.monotonic()

    # Get filenames for context
    doc_names = {}
    for doc_id in classified:
        doc = db.query(Document).filter_by(id=doc_id).first()
        if doc:
            doc_names[doc_id] = doc.filename

    # Serialize conflicts including taxonomy fields
    conflicts_for_report = [
        {
            "doc_a_id": c["doc_a_id"],
            "doc_b_id": c["doc_b_id"],
            "field": c["field"],
            "value_a": c["value_a"],
            "value_b": c["value_b"],
            "description": c["description"],
            "conflict_type": c["conflict_type"],
            "severity": c["severity"],
        }
        for c in conflicts
    ]

    prompt = REPORT_GENERATION_PROMPT.format(
        classified_docs_json=json.dumps(
            {doc_id: {"type": t, "filename": doc_names.get(doc_id, "unknown")}
             for doc_id, t in classified.items()}, indent=2
        ),
        facts_json=json.dumps(facts, indent=2)[:6000],
        conflicts_json=json.dumps(conflicts_for_report, indent=2),
        timeline_json=json.dumps(timeline_events, indent=2)[:3000],
    )

    try:
        report_html, tok_in, tok_out = call_llm(prompt)
        duration = int((time.monotonic() - t0) * 1000)
        log_node(db, run_id, "report_generation", stage=1,
                 decision=NodeDecision.CONTINUE,
                 output_summary=f"report generated ({len(report_html)} chars)",
                 duration_ms=duration, tokens_in=tok_in, tokens_out=tok_out)
        return {"report_html": report_html}
    except Exception as e:
        log_node(db, run_id, "report_generation", stage=1,
                 decision=NodeDecision.SKIP, error_detail=str(e))
        return {"report_html": f"<p>Report generation failed: {e}</p>"}

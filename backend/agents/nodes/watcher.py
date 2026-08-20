"""
WatcherNode — Stage 3.
Handles new documents arriving after the initial run.

Design principles:
  - Every Stage 3 update goes through a human review gate — not just conflicting updates.
    The brief requires "approve or reject before commit", unconditionally.
  - The report addendum is generated deterministically from extracted facts (no LLM diff).
    String-replacing LLM-generated 'old_content' against real HTML is too fragile.
    The DIFF_UPDATE_PROMPT is used only to detect affected sections and conflicts for
    the review item body and report_diff metadata — not to rewrite HTML.
  - new_doc_ids is cleared from state when done so re-invoke is a no-op.
"""
import time
import json
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy.orm import Session

from agents.state import GraphState, NodeDecision, ReportChange
from agents.nodes.base import safe_wrap, log_node, parse_json_safe
from agents.prompts import CLASSIFY_PROMPT, EXTRACT_PROMPT
from db.models import Document, DocumentStatus, ReviewItem
from services.llm_client import call_llm


# Used only for extracting affected-section metadata and conflicts.
# NOT used to generate the updated report_html (that is done deterministically).
DIFF_ANALYSIS_PROMPT = """You are a senior insurance claims analyst reviewing a new document.

IMPORTANT: Respond with valid JSON only. No explanation, no prose.

An existing report has been finalised. A new document has now arrived.
Identify:
1. Which sections of the existing report this new document is relevant to
2. Whether any facts in the new document contradict the existing report

Existing report summary (truncated):
{existing_report}

New document facts:
{new_facts_json}

New document type: {new_doc_type}

Respond with this JSON and nothing else:
{{
  "affected_sections": ["<section name>"],
  "new_conflicts": [
    {{
      "description": "<what contradicts what>",
      "existing_claim": "<what the report said>",
      "new_document_says": "<what the new doc says>"
    }}
  ]
}}"""


def _build_addendum_html(
    new_doc_ids: list[str],
    all_new_facts: list[dict],
    affected_sections: list[str],
    new_conflicts: list[dict],
    doc_filenames: dict[str, str],
) -> str:
    """
    Build a deterministic Stage 3 addendum section from extracted facts.
    This approach never fails due to string-matching or LLM formatting issues.
    """
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    sections_text = ", ".join(affected_sections) if affected_sections else "general"

    # Facts list — group by source doc
    fact_rows = []
    for f in all_new_facts[:30]:  # cap to keep report readable
        confidence_pct = int(f.get("confidence", 0) * 100)
        claim = f.get("claim", "").replace("<", "&lt;").replace(">", "&gt;")
        excerpt = (f.get("source_excerpt", "") or "")[:140].replace("<", "&lt;").replace(">", "&gt;")
        source = doc_filenames.get(f.get("source_doc_id", ""), f.get("source_doc_id", ""))
        badge_class = "badge-high" if confidence_pct >= 90 else "badge-med" if confidence_pct >= 70 else "badge-low"
        fact_rows.append(
            f'<tr><td>{claim}</td>'
            f'<td><span class="conf-badge {badge_class}">{confidence_pct}%</span></td>'
            f'<td><em>{excerpt}</em></td>'
            f'<td>{source}</td></tr>'
        )
    facts_html = (
        '<table class="stage3-facts">'
        '<thead><tr><th>Fact</th><th>Confidence</th><th>Source excerpt</th><th>Document</th></tr></thead>'
        f'<tbody>{"".join(fact_rows)}</tbody>'
        '</table>'
        if fact_rows else "<p>No new verifiable facts extracted.</p>"
    )

    # Conflicts section
    conflicts_html = ""
    if new_conflicts:
        conflict_rows = "".join(
            f'<li class="conflict-item">'
            f'<strong>{c.get("description", "").replace("<", "&lt;")}</strong><br>'
            f'<span class="existing-claim">Report said: {c.get("existing_claim", "").replace("<", "&lt;")}</span><br>'
            f'<span class="new-claim">New doc says: {c.get("new_document_says", "").replace("<", "&lt;")}</span>'
            f'</li>'
            for c in new_conflicts
        )
        conflicts_html = (
            f'<div class="stage3-conflicts">'
            f'<h4>⚠️ Conflicts with Existing Report ({len(new_conflicts)} found)</h4>'
            f'<ul>{conflict_rows}</ul>'
            f'</div>'
        )

    return (
        f'<section id="stage3-addendum" class="stage3-update" data-timestamp="{ts}">'
        f'<h3>Stage 3 — New Document Update <small>({ts})</small></h3>'
        f'<p><strong>Documents processed:</strong> {len(new_doc_ids)} &nbsp;|&nbsp; '
        f'<strong>New facts:</strong> {len(all_new_facts)} &nbsp;|&nbsp; '
        f'<strong>Affected sections:</strong> {sections_text}</p>'
        f'<h4>Extracted Facts</h4>{facts_html}'
        f'{conflicts_html}'
        f'</section>'
    )


def watcher_node(state: GraphState, db: Session) -> GraphState:
    """
    Process newly arrived documents without re-running the full pipeline.

    Always gates: any meaningful update (new facts extracted) pauses the run
    and creates a review item that a human must approve before the addendum
    commits to the final report.
    """
    run_id = state["run_id"]
    new_doc_ids = state.get("new_doc_ids", [])

    if not new_doc_ids:
        log_node(db, run_id, "watcher", stage=3,
                 decision=NodeDecision.SKIP,
                 output_summary="No new documents to process")
        return {**state, "current_node": "watcher", "last_decision": NodeDecision.SKIP}

    existing_report = state.get("report_html", "")
    existing_facts = state.get("extracted_facts", [])
    classified = state.get("classified_docs", {})
    new_conflicts: list[dict] = []
    affected_sections: list[str] = []
    all_report_changes: list[ReportChange] = []
    all_new_facts: list[dict] = []
    doc_filenames: dict[str, str] = {}  # doc_id → filename (for addendum display)

    for doc_id in new_doc_ids:
        doc: Document = db.query(Document).filter_by(id=doc_id).first()
        if not doc or not doc.raw_text:
            continue

        doc_filenames[doc_id] = doc.filename or doc_id
        t0 = time.monotonic()

        # ── Step 1: Classify ──────────────────────────────────────────────────
        classify_prompt = CLASSIFY_PROMPT.format(document=safe_wrap(doc.raw_text[:8000]))
        try:
            cls_text, _, _ = call_llm(classify_prompt)
            cls_result = parse_json_safe(cls_text)
            doc_type = cls_result.get("doc_type", "other") if isinstance(cls_result, dict) else "other"
            doc.doc_type = doc_type
            doc.status = DocumentStatus.parsed
            classified[doc_id] = doc_type
        except Exception:
            doc_type = "other"

        # ── Step 2: Extract facts ─────────────────────────────────────────────
        extract_prompt = EXTRACT_PROMPT.format(
            document=safe_wrap(doc.raw_text[:10000]),
            doc_id=doc_id, doc_type=doc_type,
        )
        new_facts: list[dict] = []
        try:
            ext_text, tok_in, tok_out = call_llm(extract_prompt)
            parsed = parse_json_safe(ext_text)
            new_facts = parsed if isinstance(parsed, list) else []
            doc.extracted_facts = new_facts
        except Exception:
            new_facts = []

        all_new_facts.extend(new_facts)

        # ── Step 3: Detect conflicts and affected sections (metadata only) ────
        # We do NOT use the LLM output to rewrite report_html — that approach
        # is too fragile.  We use it only to populate report_diff metadata and
        # the conflict list shown in the review item.
        if existing_report and new_facts:
            analysis_prompt = DIFF_ANALYSIS_PROMPT.format(
                existing_report=existing_report[:4000],
                new_facts_json=json.dumps(new_facts, indent=2)[:2000],
                new_doc_type=doc_type,
            )
            try:
                analysis_text, _, _ = call_llm(analysis_prompt)
                analysis = parse_json_safe(analysis_text)
                if isinstance(analysis, dict):
                    sections = analysis.get("affected_sections", [])
                    affected_sections.extend(s for s in sections if isinstance(s, str))
                    doc_conflicts = analysis.get("new_conflicts", [])
                    if isinstance(doc_conflicts, list):
                        new_conflicts.extend(doc_conflicts)

                    # Populate report_diff for the UI diff view
                    for conflict in doc_conflicts:
                        all_report_changes.append(ReportChange(
                            section=", ".join(sections) or "general",
                            change_type="conflict_flag",
                            old_content=str(conflict.get("existing_claim", "")),
                            new_content=str(conflict.get("new_document_says", "")),
                            reason=str(conflict.get("description", "")),
                            source_doc=doc.filename,
                        ))
            except Exception as e:
                log_node(db, run_id, "watcher_analysis", stage=3,
                         decision=NodeDecision.SKIP, error_detail=str(e))

        duration_ms = int((time.monotonic() - t0) * 1000)
        log_node(
            db, run_id, "watcher", stage=3,
            decision=NodeDecision.CONTINUE,
            input_summary=f"new doc: {doc.filename} ({doc_type})",
            output_summary=(
                f"{len(new_facts)} facts extracted, "
                f"{len(new_conflicts)} conflicts, "
                f"sections: {', '.join(affected_sections) or 'unknown'}"
            ),
            duration_ms=duration_ms,
        )

    # ── Build deterministic HTML addendum ────────────────────────────────────
    # Generated from extracted facts — always present when facts exist.
    # IMPORTANT: this addendum is NOT merged into report_html yet.
    # It is stored in pending_stage3_addendum and only committed to report_html
    # after a human approves it via the HITL gate.  GET /report returns the
    # existing report unchanged while the gate is open.
    addendum_html: Optional[str] = None
    if all_new_facts:
        addendum_html = _build_addendum_html(
            new_doc_ids, all_new_facts, affected_sections,
            new_conflicts, doc_filenames,
        )

    updated_facts = existing_facts + [f for f in all_new_facts if f]

    # ── Gate — always pause for human review when there is something to commit ──
    # Brief: "Conflicts, findings, and updates are approved or rejected by a
    # person before they commit."  Gate applies to ALL updates, not just conflicts.
    should_pause = addendum_html is not None

    if should_pause:
        # One summary item — the human decides whether to commit this entire addendum
        conflict_note = (
            f" ⚠️ {len(new_conflicts)} conflict(s) with existing report."
            if new_conflicts else " No conflicts detected."
        )
        summary = (
            f"Processed {len(new_doc_ids)} new document(s). "
            f"{len(all_new_facts)} fact(s) extracted from: "
            f"{', '.join(doc_filenames.values())}."
            f"{conflict_note} "
            f"Approve to add the Stage 3 addendum to the report; reject to discard it."
        )
        db.add(ReviewItem(
            run_id=run_id, stage=3, item_type="stage3_update",
            title=f"Stage 3 — Review update from {len(new_doc_ids)} new document(s)",
            body=summary,
            source_ref=",".join(new_doc_ids),
        ))

        # Per-conflict items so each contradiction can be decided independently
        for conflict in new_conflicts:
            db.add(ReviewItem(
                run_id=run_id, stage=3, item_type="conflict",
                title="New conflict detected",
                body=conflict.get("description", ""),
                source_ref=",".join(new_doc_ids),
            ))

        db.commit()
        log_node(
            db, run_id, "watcher", stage=3,
            decision=NodeDecision.CONTINUE,
            output_summary=(
                f"Stage 3 paused for review: "
                f"{len(all_new_facts)} new facts, {len(new_conflicts)} conflicts. "
                f"Addendum staged — awaiting human approval before commit."
            ),
        )

    return {
        **state,
        "extracted_facts": updated_facts,
        "classified_docs": classified,
        "affected_sections": affected_sections,
        "report_diff": all_report_changes,           # provenance diff for UI
        "report_html": existing_report or "",        # UNCHANGED — pending approval
        "pending_stage3_addendum": addendum_html,    # committed on approve, None otherwise
        "hitl_pending": should_pause,
        "current_node": "watcher",
        "last_decision": NodeDecision.CONTINUE,
        "new_doc_ids": [],                           # processed — clear the queue
    }

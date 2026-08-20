"""
Run management API endpoints.

POST /api/runs                   — create run + upload documents
GET  /api/runs/{run_id}          — run status + current state
POST /api/runs/{run_id}/start    — trigger Stage 1 (background)
POST /api/runs/{run_id}/resume   — resume after HITL gate
POST /api/runs/{run_id}/watch    — add new documents to watched run (Stage 3)
GET  /api/runs/{run_id}/cost     — cost breakdown per stage
GET  /api/runs/{run_id}/report   — the grounded HTML report
GET  /api/runs/{run_id}/logs     — full execution log (visible steps)
"""
import uuid
import asyncio
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, UploadFile, BackgroundTasks, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

from db.database import get_db
from db.models import Run, RunStatus, Document, StageMetric
from services.document_parser import parse_document
from agents.graph import get_graph, initial_state

router = APIRouter(prefix="/api/runs", tags=["runs"])


# ─── Request / Response models ────────────────────────────────────────────────

class RunCreateResponse(BaseModel):
    run_id: str
    status: str
    document_count: int
    message: str


class RunStatusResponse(BaseModel):
    run_id: str
    status: str
    current_stage: int
    current_node: Optional[str]
    document_count: int
    facts_extracted: int
    conflicts_found: int
    review_items_pending: int
    error: Optional[str]
    started_at: str
    completed_at: Optional[str]


class CostResponse(BaseModel):
    run_id: str
    total_cost_usd: float
    total_tokens_in: int
    total_tokens_out: int
    by_stage: list[dict]


class ResumeRequest(BaseModel):
    stage: int  # which HITL gate we're resuming past


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.post("", response_model=RunCreateResponse)
async def create_run(
    background_tasks: BackgroundTasks,
    rulebook: Optional[str] = Form(None),
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
):
    """
    Upload documents and create a run.
    Starts Stage 1 automatically in the background.
    """
    if not files:
        raise HTTPException(status_code=400, detail="At least one document required.")

    run_id = str(uuid.uuid4())
    run = Run(id=run_id, rulebook=rulebook, status=RunStatus.pending)
    db.add(run)
    db.flush()

    doc_ids = []
    parse_errors = []

    for upload in files:
        content = await upload.read()
        doc_id = str(uuid.uuid4())

        try:
            raw_text, mime_type = parse_document(content, upload.filename)
            doc = Document(
                id=doc_id,
                run_id=run_id,
                filename=upload.filename,
                mime_type=mime_type,
                raw_text=raw_text,
            )
        except ValueError as e:
            # Parse failed — record it honestly, don't silently skip
            doc = Document(
                id=doc_id,
                run_id=run_id,
                filename=upload.filename,
                parse_error=str(e),
            )
            parse_errors.append({"filename": upload.filename, "error": str(e)})

        db.add(doc)
        doc_ids.append(doc_id)

    run.status = RunStatus.running
    db.commit()

    # Start agent in background
    background_tasks.add_task(_run_agent, run_id, doc_ids, rulebook or "")

    msg = f"Run created with {len(files)} document(s)."
    if parse_errors:
        msg += f" {len(parse_errors)} file(s) failed to parse (see run logs)."

    return RunCreateResponse(
        run_id=run_id,
        status=RunStatus.running,
        document_count=len(files),
        message=msg,
    )


@router.get("/{run_id}", response_model=RunStatusResponse)
def get_run_status(run_id: str, db: Session = Depends(get_db)):
    run: Run = db.query(Run).filter_by(id=run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    from db.models import ReviewItem, ReviewItemStatus
    pending_count = db.query(ReviewItem).filter_by(
        run_id=run_id, status=ReviewItemStatus.pending
    ).count()

    # Conflicts are stored as ReviewItems (item_type="conflict"), not in the findings table
    conflicts_count = db.query(ReviewItem).filter_by(
        run_id=run_id, item_type="conflict"
    ).count()

    all_facts = []
    for doc in run.documents:
        if doc.extracted_facts:
            all_facts.extend(doc.extracted_facts)

    return RunStatusResponse(
        run_id=run_id,
        status=run.status,
        current_stage=run.current_stage,
        current_node=run.current_node,
        document_count=len(run.documents),
        facts_extracted=len(all_facts),
        conflicts_found=conflicts_count,
        review_items_pending=pending_count,
        error=run.error_message,
        started_at=run.started_at.isoformat() if run.started_at else "",
        completed_at=run.completed_at.isoformat() if run.completed_at else None,
    )


@router.post("/{run_id}/resume")
async def resume_run(
    run_id: str,
    request: ResumeRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Resume after all items at a HITL gate have been decided.
    Checks that no items are still pending before resuming.
    """
    run: Run = db.query(Run).filter_by(id=run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    if run.status != RunStatus.paused_hitl:
        raise HTTPException(status_code=400,
                            detail=f"Run is not paused (status: {run.status})")

    # Verify all items at this stage have been decided
    from db.models import ReviewItem, ReviewItemStatus
    pending = db.query(ReviewItem).filter_by(
        run_id=run_id, stage=request.stage, status=ReviewItemStatus.pending
    ).count()

    if pending > 0:
        raise HTTPException(
            status_code=400,
            detail=f"{pending} review item(s) still pending at stage {request.stage}. "
                   f"Approve or reject all items before resuming."
        )

    run.status = RunStatus.running
    db.commit()

    # Resume graph with hitl_pending=False
    background_tasks.add_task(_resume_agent, run_id)

    return {"message": f"Run {run_id} resuming from stage {request.stage}"}


@router.post("/{run_id}/watch")
async def add_watched_document(
    run_id: str,
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
):
    """Stage 3: add new documents to a completed or running run."""
    run: Run = db.query(Run).filter_by(id=run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    new_doc_ids = []
    for upload in files:
        content = await upload.read()
        doc_id = str(uuid.uuid4())
        try:
            raw_text, mime_type = parse_document(content, upload.filename)
            doc = Document(
                id=doc_id, run_id=run_id, filename=upload.filename,
                mime_type=mime_type, raw_text=raw_text,
            )
        except ValueError as e:
            doc = Document(id=doc_id, run_id=run_id,
                           filename=upload.filename, parse_error=str(e))
        db.add(doc)
        new_doc_ids.append(doc_id)

    db.commit()

    background_tasks.add_task(_run_watcher, run_id, new_doc_ids)
    return {"message": f"Added {len(files)} document(s) to watcher", "doc_ids": new_doc_ids}


@router.get("/{run_id}/cost", response_model=CostResponse)
def get_run_cost(run_id: str, db: Session = Depends(get_db)):
    run: Run = db.query(Run).filter_by(id=run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    metrics = db.query(StageMetric).filter_by(run_id=run_id).all()

    by_node = {}
    total_in = total_out = total_cost = 0

    for m in metrics:
        key = f"stage{m.stage}:{m.node_name}"
        if key not in by_node:
            by_node[key] = {"node": m.node_name, "stage": m.stage,
                            "tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0, "calls": 0}
        by_node[key]["tokens_in"]  += m.tokens_in
        by_node[key]["tokens_out"] += m.tokens_out
        by_node[key]["cost_usd"]   += m.cost_usd
        by_node[key]["calls"]      += 1
        total_in   += m.tokens_in
        total_out  += m.tokens_out
        total_cost += m.cost_usd

    return CostResponse(
        run_id=run_id,
        total_cost_usd=round(total_cost, 6),
        total_tokens_in=total_in,
        total_tokens_out=total_out,
        by_stage=list(by_node.values()),
    )


@router.get("/{run_id}/report")
def get_run_report(run_id: str, db: Session = Depends(get_db)):
    run: Run = db.query(Run).filter_by(id=run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    # Get latest state from LangGraph checkpointer
    sv = {}
    try:
        graph = get_graph()
        config = {"configurable": {"thread_id": run_id}}
        state = graph.get_state(config)
        sv = state.values or {}
    except Exception:
        sv = {}

    return {
        "run_id": run_id,
        "report_html":               sv.get("report_html", ""),
        # pending_stage3_addendum is the staged addendum awaiting human approval.
        # Non-null means Stage 3 is paused — the addendum is NOT yet in report_html.
        # The UI should show a banner rather than silently displaying staged content.
        "pending_stage3_addendum":   sv.get("pending_stage3_addendum"),
        "conflicts":                 sv.get("conflicts", []),
        "timeline_events":           sv.get("timeline_events", []),
        "fraud_signals":             sv.get("fraud_signals", []),
        "disposition_recommendation": sv.get("disposition_recommendation"),
        "report_diff":               sv.get("report_diff"),
    }


@router.get("/{run_id}/logs")
def get_run_logs(run_id: str, db: Session = Depends(get_db)):
    from db.models import RunLog
    logs = db.query(RunLog).filter_by(run_id=run_id).order_by(RunLog.created_at).all()
    return {
        "run_id": run_id,
        "logs": [
            {
                "node": l.node_name,
                "stage": l.stage,
                "decision": l.decision,
                "input": l.input_summary,
                "output": l.output_summary,
                "error": l.error_detail,
                "retries": l.retry_count,
                "duration_ms": l.duration_ms,
                "at": l.created_at.isoformat() if l.created_at else None,
            }
            for l in logs
        ]
    }


# ─── Background task helpers ──────────────────────────────────────────────────

def _sync_run_status(run: Run, final_values: dict) -> None:
    """
    Helper: write final graph state fields back to the DB Run row.
    Call this after every graph invocation that can change status.
    """
    fv = final_values or {}
    if fv.get("hitl_pending"):
        run.status = RunStatus.paused_hitl
    elif fv.get("error"):
        run.status = RunStatus.failed
        run.error_message = fv["error"]
    else:
        run.status = RunStatus.completed
        run.completed_at = datetime.utcnow()

    # Keep current_node / current_stage in the DB in sync so the status API
    # doesn't report stale node names after completion.
    if "current_node" in fv and fv["current_node"]:
        run.current_node = fv["current_node"]
    if "current_stage" in fv and fv["current_stage"]:
        run.current_stage = fv["current_stage"]


def _run_agent(run_id: str, doc_ids: list[str], rulebook: str):
    """Run the LangGraph agent to completion or HITL pause."""
    from db.database import SessionLocal
    db = SessionLocal()
    try:
        graph = get_graph()
        state = initial_state(run_id, doc_ids, rulebook)
        config = {"configurable": {"thread_id": run_id}}
        graph.invoke(state, config=config)

        final = graph.get_state(config)
        run: Run = db.query(Run).filter_by(id=run_id).first()
        if run:
            _sync_run_status(run, final.values)
            db.commit()
    except Exception as e:
        run: Run = db.query(Run).filter_by(id=run_id).first()
        if run:
            run.status = RunStatus.failed
            run.error_message = str(e)
            db.commit()
    finally:
        db.close()


def _resume_agent(run_id: str):
    """
    Resume a paused run after all HITL items at the current gate are decided.

    Stage 1 / Stage 2: the graph is parked at a hitl_gate node; set hitl_pending=False
    and graph.invoke(None) drives it forward to the next nodes.

    Stage 3: the graph is already at END (watcher_node ran directly, not via the graph).
    graph.invoke(None) on a completed graph is a no-op. For Stage 3 we only need to
    clear hitl_pending in the checkpoint and mark the run completed — the updated
    report_html is already in the checkpoint from _run_watcher.
    """
    from db.database import SessionLocal
    db = SessionLocal()
    try:
        graph = get_graph()
        config = {"configurable": {"thread_id": run_id}}

        # Read current stage before clearing the gate
        snap = graph.get_state(config)
        current_stage = (snap.values or {}).get("current_stage", 2)

        # Always clear the HITL flag in the checkpoint
        graph.update_state(config, {"hitl_pending": False})

        if current_stage == 3:
            # Stage 3: graph is at END (watcher ran directly).
            # Decide whether to commit the staged addendum or discard it based on
            # the reviewer's decision on the stage3_update review item.
            from db.models import ReviewItem, ReviewItemStatus
            snap_values = dict(snap.values or {})
            pending_addendum = snap_values.get("pending_stage3_addendum") or ""
            existing_report  = snap_values.get("report_html") or ""

            # Look at the most recent stage3_update item's decision
            stage3_item = (
                db.query(ReviewItem)
                  .filter_by(run_id=run_id, stage=3, item_type="stage3_update")
                  .order_by(ReviewItem.created_at.desc())
                  .first()
            )
            approved = (
                stage3_item is not None
                and stage3_item.status == ReviewItemStatus.approved
            )

            if approved and pending_addendum:
                # Human approved — merge addendum into report_html now
                committed_report = existing_report + pending_addendum
                graph.update_state(config, {
                    "hitl_pending": False,
                    "report_html": committed_report,
                    "pending_stage3_addendum": None,
                })
                final_values = {
                    **snap_values,
                    "hitl_pending": False,
                    "report_html": committed_report,
                    "pending_stage3_addendum": None,
                }
            else:
                # Rejected or no pending addendum — discard staging, keep existing report
                graph.update_state(config, {
                    "hitl_pending": False,
                    "pending_stage3_addendum": None,
                })
                final_values = {
                    **snap_values,
                    "hitl_pending": False,
                    "pending_stage3_addendum": None,
                }
        else:
            # Stage 1 / Stage 2: continue from the hitl_gate node
            graph.invoke(None, config=config)
            final_snap = graph.get_state(config)
            final_values = final_snap.values or {}

        run: Run = db.query(Run).filter_by(id=run_id).first()
        if run:
            _sync_run_status(run, final_values)
            db.commit()
    except Exception as e:
        run: Run = db.query(Run).filter_by(id=run_id).first()
        if run:
            run.status = RunStatus.failed
            run.error_message = str(e)
            db.commit()
    finally:
        db.close()


def _run_watcher(run_id: str, new_doc_ids: list[str]):
    """
    Trigger Stage 3 watcher for newly arrived documents.

    IMPORTANT: A completed LangGraph graph is at END and graph.invoke(None) is a
    no-op on it — it returns current state without executing any nodes.  We call
    watcher_node() directly instead, then persist the result back via update_state
    so get_report() sees the updated report_html and report_diff.
    """
    from db.database import SessionLocal
    from agents.nodes.watcher import watcher_node as _watcher_node
    db = SessionLocal()
    try:
        graph = get_graph()
        config = {"configurable": {"thread_id": run_id}}

        # Load the current checkpoint state
        snap = graph.get_state(config)
        current = dict(snap.values) if snap.values else {}

        # Build watcher input with new docs queued
        watcher_input = {
            **current,
            "new_doc_ids": new_doc_ids,
            "hitl_pending": False,
        }

        # Call node directly — bypasses the dead graph.invoke() on a completed run
        result = _watcher_node(watcher_input, db)

        # Persist updated report_html, report_diff, and control fields back to checkpoint
        graph.update_state(config, result)

        run: Run = db.query(Run).filter_by(id=run_id).first()
        if run:
            if result.get("hitl_pending"):
                run.status = RunStatus.paused_hitl
                run.current_stage = 3
                run.current_node = "watcher"
            else:
                run.status = RunStatus.completed
                run.current_node = "watcher"
                run.current_stage = 3
                run.completed_at = datetime.utcnow()
            db.commit()
    except Exception as e:
        run: Run = db.query(Run).filter_by(id=run_id).first()
        if run:
            run.status = RunStatus.failed
            run.error_message = str(e)
            db.commit()
        print(f"Watcher failed for run {run_id}: {e}")
    finally:
        db.close()

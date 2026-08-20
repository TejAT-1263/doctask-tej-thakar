"""
HITL Review API endpoints.

GET  /api/runs/{run_id}/review          — list pending review items
POST /api/runs/{run_id}/review/{item_id}/approve  — approve one item
POST /api/runs/{run_id}/review/{item_id}/reject   — reject one item (with note)
GET  /api/runs/{run_id}/review/summary  — approved/rejected counts
"""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

from db.database import get_db
from db.models import ReviewItem, ReviewItemStatus, Run

router = APIRouter(prefix="/api/runs", tags=["review"])


class ReviewDecision(BaseModel):
    reviewer_note: Optional[str] = None


class ReviewItemOut(BaseModel):
    id: str
    stage: int
    item_type: str
    title: str
    body: str
    source_ref: Optional[str]
    status: str
    reviewer_note: Optional[str]
    created_at: str


@router.get("/{run_id}/review")
def list_review_items(
    run_id: str,
    stage: Optional[int] = None,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """List review items for a run. Filter by stage and/or status."""
    query = db.query(ReviewItem).filter_by(run_id=run_id)
    if stage is not None:
        query = query.filter_by(stage=stage)
    if status:
        query = query.filter_by(status=ReviewItemStatus(status))

    items = query.order_by(ReviewItem.created_at).all()

    return {
        "run_id": run_id,
        "items": [
            {
                "id": item.id,
                "stage": item.stage,
                "item_type": item.item_type,
                "title": item.title,
                "body": item.body,
                "source_ref": item.source_ref,
                "status": item.status,
                "reviewer_note": item.reviewer_note,
                "created_at": item.created_at.isoformat() if item.created_at else None,
            }
            for item in items
        ],
        "total": len(items),
        "pending": sum(1 for i in items if i.status == ReviewItemStatus.pending),
    }


@router.post("/{run_id}/review/{item_id}/approve")
def approve_item(
    run_id: str,
    item_id: str,
    decision: ReviewDecision,
    db: Session = Depends(get_db),
):
    """
    Approve a single review item.
    Approving one item does NOT affect any other items in the run.
    """
    item = db.query(ReviewItem).filter_by(id=item_id, run_id=run_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Review item not found")

    if item.status != ReviewItemStatus.pending:
        raise HTTPException(
            status_code=400,
            detail=f"Item already decided: {item.status}. Cannot re-decide."
        )

    item.status = ReviewItemStatus.approved
    item.reviewer_note = decision.reviewer_note
    item.decided_at = datetime.utcnow()
    db.commit()

    return {
        "id": item_id,
        "status": "approved",
        "message": "Item approved. Other items in this run are unaffected.",
    }


@router.post("/{run_id}/review/{item_id}/reject")
def reject_item(
    run_id: str,
    item_id: str,
    decision: ReviewDecision,
    db: Session = Depends(get_db),
):
    """
    Reject a single review item with an optional note.
    Rejecting does NOT discard other items — only this one.
    """
    item = db.query(ReviewItem).filter_by(id=item_id, run_id=run_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Review item not found")

    if item.status != ReviewItemStatus.pending:
        raise HTTPException(
            status_code=400,
            detail=f"Item already decided: {item.status}. Cannot re-decide."
        )

    item.status = ReviewItemStatus.rejected
    item.reviewer_note = decision.reviewer_note
    item.decided_at = datetime.utcnow()
    db.commit()

    return {
        "id": item_id,
        "status": "rejected",
        "reviewer_note": decision.reviewer_note,
        "message": "Item rejected. Other items in this run are unaffected.",
    }


@router.get("/{run_id}/review/summary")
def review_summary(run_id: str, db: Session = Depends(get_db)):
    """How many items are pending / approved / rejected, by stage."""
    items = db.query(ReviewItem).filter_by(run_id=run_id).all()

    by_stage: dict[int, dict] = {}
    for item in items:
        s = item.stage
        if s not in by_stage:
            by_stage[s] = {"stage": s, "pending": 0, "approved": 0, "rejected": 0, "total": 0}
        by_stage[s][item.status.value] += 1
        by_stage[s]["total"] += 1

    return {
        "run_id": run_id,
        "by_stage": list(by_stage.values()),
        "all_decided": all(i.status != ReviewItemStatus.pending for i in items),
    }

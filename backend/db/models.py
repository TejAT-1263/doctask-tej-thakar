"""
Database models for the DocTask agentic system.
Every table is partitioned by run_id — concurrent runs never share state.
"""
import uuid
from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import (
    Column, String, Text, Integer, Float, Boolean,
    DateTime, ForeignKey, JSON, Enum, Index
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.types import TypeDecorator

try:
    from pgvector.sqlalchemy import Vector
except ModuleNotFoundError:
    class Vector(TypeDecorator):
        """
        Lightweight fallback so SQLite-backed tests can run without pgvector installed.
        Stores vectors as JSON arrays in non-Postgres test environments.
        """
        impl = JSON
        cache_ok = True

        def __init__(self, dimension: int, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.dimension = dimension

from db.database import Base


def new_uuid() -> str:
    return str(uuid.uuid4())


# ─────────────────────────────────────────────
# Enums
# ─────────────────────────────────────────────

class RunStatus(str, PyEnum):
    pending       = "pending"
    running       = "running"
    paused_hitl   = "paused_hitl"   # waiting for human gate
    completed     = "completed"
    failed        = "failed"
    cancelled     = "cancelled"


class NodeDecision(str, PyEnum):
    continue_  = "continue"
    retry      = "retry"
    skip       = "skip"
    escalate   = "escalate"


class ReviewItemStatus(str, PyEnum):
    pending   = "pending"
    approved  = "approved"
    rejected  = "rejected"


class DocumentStatus(str, PyEnum):
    pending    = "pending"
    parsed     = "parsed"
    failed     = "failed"


# ─────────────────────────────────────────────
# Runs
# ─────────────────────────────────────────────

class Run(Base):
    """One end-to-end analysis run over a document pile."""
    __tablename__ = "runs"

    id          = Column(String, primary_key=True, default=new_uuid)
    status      = Column(Enum(RunStatus), default=RunStatus.pending, nullable=False)
    domain      = Column(String(100), default="insurance_claims")
    rulebook    = Column(Text, nullable=True)  # user-supplied checklist / rules
    current_stage = Column(Integer, default=1)  # 1=understand, 2=examine, 3=watch
    current_node  = Column(String(100), nullable=True)  # last completed node name
    error_message = Column(Text, nullable=True)

    # LangGraph checkpoint thread_id (== run.id for simplicity)
    checkpoint_thread_id = Column(String, nullable=True)

    # Timing / cost
    started_at    = Column(DateTime, default=datetime.utcnow)
    completed_at  = Column(DateTime, nullable=True)
    total_cost_usd = Column(Float, default=0.0)

    documents    = relationship("Document", back_populates="run", cascade="all, delete-orphan")
    run_logs     = relationship("RunLog", back_populates="run", cascade="all, delete-orphan")
    findings     = relationship("Finding", back_populates="run", cascade="all, delete-orphan")
    review_items = relationship("ReviewItem", back_populates="run", cascade="all, delete-orphan")
    stage_metrics = relationship("StageMetric", back_populates="run", cascade="all, delete-orphan")


# ─────────────────────────────────────────────
# Documents
# ─────────────────────────────────────────────

class Document(Base):
    """A single source document in a run's pile."""
    __tablename__ = "documents"

    id         = Column(String, primary_key=True, default=new_uuid)
    run_id     = Column(String, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    filename   = Column(String(255), nullable=False)
    mime_type  = Column(String(100), nullable=True)
    doc_type   = Column(String(100), nullable=True)  # e.g. "claim_form", "policy_document"
    status     = Column(Enum(DocumentStatus), default=DocumentStatus.pending)
    raw_text   = Column(Text, nullable=True)
    parsed_html = Column(Text, nullable=True)

    # SuperDocs session/document IDs (populated after upload)
    superdocs_session_id = Column(String, nullable=True)
    superdocs_doc_id     = Column(String, nullable=True)

    # Extracted facts (list of ExtractedFact dicts)
    extracted_facts = Column(JSON, default=list)

    # Vector embedding of document summary (for conflict detection)
    embedding = Column(Vector(1536), nullable=True)

    parse_error = Column(Text, nullable=True)
    uploaded_at = Column(DateTime, default=datetime.utcnow)

    run = relationship("Run", back_populates="documents")

    __table_args__ = (
        Index("ix_documents_run_id", "run_id"),
    )


# ─────────────────────────────────────────────
# Run execution log (visible steps)
# ─────────────────────────────────────────────

class RunLog(Base):
    """One entry per node execution — makes steps visible."""
    __tablename__ = "run_logs"

    id         = Column(String, primary_key=True, default=new_uuid)
    run_id     = Column(String, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    node_name  = Column(String(100), nullable=False)
    stage      = Column(Integer, nullable=False)
    decision   = Column(Enum(NodeDecision), nullable=True)
    input_summary  = Column(Text, nullable=True)
    output_summary = Column(Text, nullable=True)
    error_detail   = Column(Text, nullable=True)
    retry_count    = Column(Integer, default=0)
    duration_ms    = Column(Integer, nullable=True)
    created_at     = Column(DateTime, default=datetime.utcnow)

    run = relationship("Run", back_populates="run_logs")

    __table_args__ = (
        Index("ix_run_logs_run_id", "run_id"),
    )


# ─────────────────────────────────────────────
# Findings (from Stage 2 rule check)
# ─────────────────────────────────────────────

class Finding(Base):
    """A single rule-check finding — always points to a source."""
    __tablename__ = "findings"

    id          = Column(String, primary_key=True, default=new_uuid)
    run_id      = Column(String, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    rule_text   = Column(Text, nullable=False)
    finding_text = Column(Text, nullable=False)
    severity    = Column(String(20), default="info")  # info | warning | critical
    is_conflict = Column(Boolean, default=False)

    # Source citation — every finding must have one
    source_doc_id  = Column(String, ForeignKey("documents.id"), nullable=True)
    source_excerpt = Column(Text, nullable=True)
    source_page    = Column(Integer, nullable=True)
    is_verified    = Column(Boolean, default=True)  # False = AI couldn't find evidence

    created_at = Column(DateTime, default=datetime.utcnow)

    run = relationship("Run", back_populates="findings")

    __table_args__ = (
        Index("ix_findings_run_id", "run_id"),
    )


# ─────────────────────────────────────────────
# Review items (HITL gate)
# ─────────────────────────────────────────────

class ReviewItem(Base):
    """
    One item waiting for human approval.
    Approving one does NOT affect the others.
    Rejecting one does NOT discard the rest.
    """
    __tablename__ = "review_items"

    id          = Column(String, primary_key=True, default=new_uuid)
    run_id      = Column(String, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    stage       = Column(Integer, nullable=False)  # 1 or 2
    item_type   = Column(String(50), nullable=False)  # "finding" | "conflict" | "report_section"
    title       = Column(String(255), nullable=False)
    body        = Column(Text, nullable=False)     # what the human reviews
    source_ref  = Column(String, nullable=True)   # FK to finding.id or document.id
    status      = Column(Enum(ReviewItemStatus), default=ReviewItemStatus.pending)
    reviewer_note = Column(Text, nullable=True)
    decided_at  = Column(DateTime, nullable=True)
    created_at  = Column(DateTime, default=datetime.utcnow)

    run = relationship("Run", back_populates="review_items")

    __table_args__ = (
        Index("ix_review_items_run_id_stage", "run_id", "stage"),
    )


# ─────────────────────────────────────────────
# Stage metrics (cost + timing per node)
# ─────────────────────────────────────────────

class StageMetric(Base):
    """Per-node cost and timing — so /runs/{id}/cost works."""
    __tablename__ = "stage_metrics"

    id           = Column(String, primary_key=True, default=new_uuid)
    run_id       = Column(String, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    node_name    = Column(String(100), nullable=False)
    stage        = Column(Integer, nullable=False)
    tokens_in    = Column(Integer, default=0)
    tokens_out   = Column(Integer, default=0)
    latency_ms   = Column(Integer, default=0)
    cost_usd     = Column(Float, default=0.0)
    created_at   = Column(DateTime, default=datetime.utcnow)

    run = relationship("Run", back_populates="stage_metrics")

    __table_args__ = (
        Index("ix_stage_metrics_run_id", "run_id"),
    )

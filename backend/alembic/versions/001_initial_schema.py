"""Initial schema — all 6 tables + pgvector extension

Revision ID: 001
Revises:
Create Date: 2026-08-10
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enable pgvector extension before creating tables
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # ── runs ────────────────────────────────────────────────────────────────
    op.create_table(
        "runs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "status",
            sa.Enum(
                "pending", "running", "paused_hitl", "completed", "failed",
                name="runstatus",
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("domain", sa.String(), nullable=False),
        sa.Column("rulebook", sa.Text(), nullable=True),
        sa.Column("current_stage", sa.Integer(), nullable=True),
        sa.Column("current_node", sa.String(), nullable=True),
        sa.Column("checkpoint_thread_id", sa.String(), nullable=True),
        sa.Column("total_cost_usd", sa.Float(), nullable=True, server_default="0.0"),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("now()"),
            onupdate=sa.text("now()"),
        ),
    )

    # ── documents ───────────────────────────────────────────────────────────
    op.create_table(
        "documents",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("run_id", sa.String(), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("filename", sa.String(), nullable=False),
        sa.Column("mime_type", sa.String(), nullable=True),
        sa.Column("doc_type", sa.String(), nullable=True),
        sa.Column("raw_text", sa.Text(), nullable=True),
        sa.Column("superdocs_session_id", sa.String(), nullable=True),
        sa.Column("superdocs_doc_id", sa.String(), nullable=True),
        sa.Column("extracted_facts", postgresql.JSONB(), nullable=True),
        # Vector column — pgvector must be enabled first
        sa.Column(
            "embedding",
            sa.Text(),  # placeholder; actual vector type added below via raw SQL
            nullable=True,
        ),
        sa.Column("parse_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    # Replace placeholder with actual vector type
    op.execute("ALTER TABLE documents ALTER COLUMN embedding TYPE vector(1536) USING NULL")
    op.create_index("ix_documents_run_id", "documents", ["run_id"])

    # ── run_logs ────────────────────────────────────────────────────────────
    op.create_table(
        "run_logs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.String(), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("node_name", sa.String(), nullable=False),
        sa.Column("stage", sa.Integer(), nullable=True),
        sa.Column(
            "decision",
            sa.Enum("CONTINUE", "RETRY", "SKIP", "ESCALATE", name="nodedecision"),
            nullable=True,
        ),
        sa.Column("input_summary", sa.Text(), nullable=True),
        sa.Column("output_summary", sa.Text(), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_run_logs_run_id", "run_logs", ["run_id"])

    # ── findings ────────────────────────────────────────────────────────────
    op.create_table(
        "findings",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.String(), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("rule_text", sa.Text(), nullable=True),
        sa.Column("finding_text", sa.Text(), nullable=True),
        sa.Column("severity", sa.String(), nullable=True),
        sa.Column("is_conflict", sa.Boolean(), nullable=True, server_default="false"),
        sa.Column("source_doc_id", sa.String(), sa.ForeignKey("documents.id"), nullable=True),
        sa.Column("source_excerpt", sa.Text(), nullable=True),
        sa.Column("source_page", sa.Integer(), nullable=True),
        sa.Column("is_verified", sa.Boolean(), nullable=True, server_default="false"),
    )
    op.create_index("ix_findings_run_id", "findings", ["run_id"])

    # ── review_items ────────────────────────────────────────────────────────
    op.create_table(
        "review_items",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("run_id", sa.String(), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("stage", sa.Integer(), nullable=False),
        sa.Column("item_type", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("source_ref", sa.String(), nullable=True),
        sa.Column(
            "status",
            sa.Enum("pending", "approved", "rejected", name="reviewitemstatus"),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("reviewer_note", sa.Text(), nullable=True),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_review_items_run_id", "review_items", ["run_id"])
    op.create_index("ix_review_items_run_stage", "review_items", ["run_id", "stage"])

    # ── stage_metrics ───────────────────────────────────────────────────────
    op.create_table(
        "stage_metrics",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.String(), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("node_name", sa.String(), nullable=False),
        sa.Column("stage", sa.Integer(), nullable=True),
        sa.Column("tokens_in", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("tokens_out", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("cost_usd", sa.Float(), nullable=True, server_default="0.0"),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_stage_metrics_run_id", "stage_metrics", ["run_id"])

    # pgvector IVFFlat index for fast similarity search
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_documents_embedding_ivfflat "
        "ON documents USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
    )


def downgrade() -> None:
    op.drop_index("ix_documents_embedding_ivfflat", table_name="documents")
    op.drop_table("stage_metrics")
    op.drop_table("review_items")
    op.drop_table("findings")
    op.drop_table("run_logs")
    op.drop_table("documents")
    op.drop_table("runs")
    op.execute("DROP TYPE IF EXISTS reviewitemstatus")
    op.execute("DROP TYPE IF EXISTS nodedecision")
    op.execute("DROP TYPE IF EXISTS runstatus")
    op.execute("DROP EXTENSION IF EXISTS vector")

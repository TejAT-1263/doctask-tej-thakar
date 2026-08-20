"""
Embedding service — RAG pipeline for DocTask.
=============================================
Generates 1536-dim vectors using OpenAI text-embedding-3-small and stores them in the
Document.embedding column (pgvector Vector(1536)).

Graceful degradation: if OPENAI_API_KEY is not set, every function continues to work
but returns empty results. The pipeline never crashes due to a missing embedding key.

Public API
----------
  generate_embedding(text)              -> list[float]
  embed_and_store(doc, db)              -> None          (called by extract_node)
  retrieve_similar_facts(query_text, db, exclude_run_id, limit) -> list[dict]
  search_similar_to_doc(doc_id, db, limit) -> list[dict] (REST endpoint helper)
  search_by_text(query, db, limit, run_id) -> list[dict] (REST endpoint helper)
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

from sqlalchemy.orm import Session
from sqlalchemy import text as sql_text
from config import get_settings

if TYPE_CHECKING:
    from db.models import Document

logger = logging.getLogger(__name__)

EMBEDDING_DIM = 1536
_ZERO_VECTOR: list[float] = [0.0] * EMBEDDING_DIM


# ─── Core embedding call ──────────────────────────────────────────────────────

def generate_embedding(text: str) -> list[float]:
    """
    Return a 1536-dim embedding vector for text using OpenAI text-embedding-3-small.
    Falls back to a zero vector if the key is missing or the call fails.
    Never raises — callers can check _is_zero() to detect the fallback.
    """
    settings = get_settings()

    if not settings.openai_api_key:
        logger.debug("OPENAI_API_KEY not configured — returning zero vector")
        return list(_ZERO_VECTOR)

    try:
        import openai
        client = openai.OpenAI(api_key=settings.openai_api_key)
        # Clip to ~8k tokens to stay within model context limits
        response = client.embeddings.create(
            model="text-embedding-3-small",
            input=text[:20000],
        )
        return response.data[0].embedding
    except Exception as exc:
        logger.error(f"OpenAI embedding call failed: {exc}")
        return list(_ZERO_VECTOR)


def _is_zero(vec: list[float]) -> bool:
    return all(v == 0.0 for v in vec)


def _vec_to_pg_literal(vec: list[float]) -> str:
    """Convert a Python float list to the string literal pgvector expects: '[0.1,0.2,...]'"""
    return "[" + ",".join(f"{v:.8f}" for v in vec) + "]"


# ─── Store ────────────────────────────────────────────────────────────────────

def embed_and_store(doc: "Document", db: Session) -> None:
    """
    Generate an embedding for doc.raw_text and persist it to the DB.
    Called by the extract node after facts are extracted so we embed the
    actual ingested text (not the upload path).

    Skips silently if:
    - doc.raw_text is empty
    - generate_embedding() returns a zero vector (key missing / API error)
    """
    if not doc.raw_text:
        return

    vector = generate_embedding(doc.raw_text)
    if _is_zero(vector):
        logger.debug(f"Skipping embedding storage for doc {doc.id} (zero vector)")
        return

    doc.embedding = vector
    db.commit()
    logger.info(f"Stored {len(vector)}-dim embedding for doc {doc.id} ({doc.filename})")


# ─── Retrieve (RAG context injection) ────────────────────────────────────────

def retrieve_similar_facts(
    query_text: str,
    db: Session,
    exclude_run_id: str,
    limit: int = 3,
) -> list[dict]:
    """
    Find documents from previous runs whose embeddings are closest to query_text.
    Returns their doc_type, filename, similarity score, and extracted_facts list.

    Used by extract_node to inject context from similar past claims into the
    extraction prompt, improving consistency across related documents.

    Returns [] if embeddings are disabled (zero-vector fallback) or if no
    similar documents exist yet (e.g., first claim in the system).
    """
    # Use the first 2000 chars for the query vector — fast and sufficient for retrieval
    query_vec = generate_embedding(query_text[:2000])
    if _is_zero(query_vec):
        return []

    vec_literal = _vec_to_pg_literal(query_vec)

    sql = """
        SELECT
            d.id              AS doc_id,
            d.doc_type        AS doc_type,
            d.filename        AS filename,
            d.extracted_facts AS extracted_facts,
            d.embedding <=> CAST(:vec AS vector) AS distance
        FROM documents d
        WHERE d.embedding IS NOT NULL
          AND d.run_id != :exclude_run_id
        ORDER BY distance ASC
        LIMIT :limit
    """
    try:
        rows = db.execute(
            sql_text(sql),
            {"vec": vec_literal, "exclude_run_id": str(exclude_run_id), "limit": limit},
        ).fetchall()
    except Exception as exc:
        logger.error(f"retrieve_similar_facts query failed: {exc}")
        return []

    results = []
    for r in rows:
        results.append({
            "doc_id": str(r.doc_id),
            "doc_type": r.doc_type,
            "filename": r.filename,
            "distance": float(r.distance),
            "similarity": round(1.0 - float(r.distance), 4),
            "extracted_facts": r.extracted_facts or [],
        })
    return results


# ─── Search (REST endpoints) ──────────────────────────────────────────────────

def search_similar_to_doc(
    doc_id: str,
    db: Session,
    limit: int = 5,
) -> list[dict]:
    """
    Find documents whose embeddings are closest to a given document's stored embedding.
    Used by GET /api/search/similar?doc_id=...

    Returns [] if the document has no embedding yet (not yet processed).
    """
    from db.models import Document

    doc: Optional[Document] = db.query(Document).filter_by(id=doc_id).first()
    if not doc or doc.embedding is None:
        return []

    vec_literal = _vec_to_pg_literal(list(doc.embedding))

    sql = """
        SELECT
            d.id        AS doc_id,
            d.run_id    AS run_id,
            d.doc_type  AS doc_type,
            d.filename AS filename,
            d.embedding <=> CAST(:vec AS vector) AS distance
        FROM documents d
        WHERE d.id    != :exclude_doc_id
          AND d.embedding IS NOT NULL
        ORDER BY distance ASC
        LIMIT :limit
    """
    try:
        rows = db.execute(
            sql_text(sql),
            {"vec": vec_literal, "exclude_doc_id": doc_id, "limit": limit},
        ).fetchall()
    except Exception as exc:
        logger.error(f"search_similar_to_doc query failed: {exc}")
        return []

    return [
        {
            "doc_id": str(r.doc_id),
            "run_id": str(r.run_id),
            "doc_type": r.doc_type,
            "filename": r.filename,
            "distance": float(r.distance),
            "similarity": round(1.0 - float(r.distance), 4),
        }
        for r in rows
    ]


def search_by_text(
    query: str,
    db: Session,
    limit: int = 5,
    run_id: Optional[str] = None,
) -> list[dict]:
    """
    Semantic search using a free-text query.
    Optionally scoped to documents from a single run.
    Used by GET /api/search?q=...
    """
    query_vec = generate_embedding(query)
    if _is_zero(query_vec):
        return []

    vec_literal = _vec_to_pg_literal(query_vec)
    run_clause = ""
    params: dict = {"vec": vec_literal, "limit": limit}

    if run_id:
        run_clause = "AND d.run_id = :run_id"
        params["run_id"] = run_id

    sql = f"""
        SELECT
            d.id        AS doc_id,
            d.run_id    AS run_id,
            d.doc_type  AS doc_type,
            d.filename AS filename,
            d.embedding <=> CAST(:vec AS vector) AS distance
        FROM documents d
        WHERE d.embedding IS NOT NULL
          {run_clause}
        ORDER BY distance ASC
        LIMIT :limit
    """
    try:
        rows = db.execute(sql_text(sql), params).fetchall()
    except Exception as exc:
        logger.error(f"search_by_text query failed: {exc}")
        return []

    return [
        {
            "doc_id": str(r.doc_id),
            "run_id": str(r.run_id),
            "doc_type": r.doc_type,
            "filename": r.filename,
            "distance": float(r.distance),
            "similarity": round(1.0 - float(r.distance), 4),
        }
        for r in rows
    ]

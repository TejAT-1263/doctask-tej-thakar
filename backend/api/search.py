"""
Search API — semantic similarity search over embedded documents.

Endpoints
---------
GET /api/search
    ?q=<text>           — free-text semantic search across all embedded documents
    ?run_id=<uuid>      — optional: scope results to a single run
    ?limit=<int>        — max results (default 5, max 20)

GET /api/search/similar
    ?doc_id=<uuid>      — find documents similar to a given embedded document
    ?limit=<int>        — max results (default 5, max 20)

Both endpoints return an empty list (not an error) when:
  - OPENAI_API_KEY is not configured
  - The queried document has no stored embedding yet
  - No similar documents exist in the DB

This allows the rest of the system to operate normally even when the embedding
pipeline is not yet active.
"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from db.database import get_db
from services.embeddings import search_by_text, search_similar_to_doc

router = APIRouter(prefix="/api/search", tags=["search"])


@router.get("", summary="Semantic text search")
def semantic_search(
    q: str = Query(..., description="Free-text query to search for similar documents"),
    run_id: Optional[str] = Query(None, description="Scope results to a single run"),
    limit: int = Query(5, ge=1, le=20, description="Max results to return"),
    db: Session = Depends(get_db),
) -> dict:
    """
    Search for documents whose content is semantically similar to the query string.

    Uses pgvector cosine similarity on stored OpenAI text-embedding-3-small vectors.
    Returns results ordered by similarity (highest first).

    Returns an empty list if embeddings are not configured — never errors.
    """
    if not q.strip():
        raise HTTPException(status_code=400, detail="q must not be empty")

    results = search_by_text(query=q, db=db, limit=limit, run_id=run_id)
    return {
        "query": q,
        "run_id": run_id,
        "count": len(results),
        "results": results,
    }


@router.get("/similar", summary="Find similar documents by doc_id")
def similar_docs(
    doc_id: str = Query(..., description="UUID of the source document"),
    limit: int = Query(5, ge=1, le=20, description="Max results to return"),
    db: Session = Depends(get_db),
) -> dict:
    """
    Find documents whose embeddings are closest to a given document.

    Useful for surfacing related claims when reviewing a specific document —
    e.g., 'show me other policies similar to this one'.

    Returns an empty list if the document has no embedding yet.
    """
    results = search_similar_to_doc(doc_id=doc_id, db=db, limit=limit)
    return {
        "doc_id": doc_id,
        "count": len(results),
        "results": results,
    }

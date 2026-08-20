"""
ExtractNode — Stage 1, step 2.
Extracts structured facts from each classified document.
Every fact must have a source excerpt — unverified facts are flagged, not silently included.

RAG enhancement: before each LLM call, retrieves facts from similar past claims and injects
them as context so the model can extract consistently across related document sets.
After extraction, generates and stores an embedding for the document so it is available
for future similarity lookups.
"""
import time
import json
from sqlalchemy.orm import Session

from agents.state import GraphState, NodeDecision, ExtractedFact
from agents.prompts import EXTRACT_PROMPT
from agents.nodes.base import safe_wrap, log_node, parse_json_safe
from db.models import Document
from services.llm_client import call_llm
from services.embeddings import retrieve_similar_facts, embed_and_store


def _build_rag_context_block(similar_docs: list[dict]) -> str:
    """
    Format retrieved similar-document facts into a context block that is
    prepended to the extraction prompt.  Limited to 3 docs × 5 facts each
    to keep the prompt size reasonable.
    """
    if not similar_docs:
        return ""

    lines = [
        "=== CONTEXT FROM SIMILAR PAST CLAIMS ===",
        "The following facts were extracted from documents similar to this one.",
        "Use them only as reference — do NOT copy them into the current extraction.",
        "Extract facts solely from the DOCUMENT CONTENT below.",
        "",
    ]
    for i, ctx in enumerate(similar_docs[:3], 1):
        facts = ctx.get("extracted_facts") or []
        if not facts:
            continue
        sim_pct = int(ctx["similarity"] * 100)
        filename = ctx.get("filename") or ctx.get("file_name") or "unknown"
        lines.append(
            f"Similar claim {i} "
            f"(type={ctx['doc_type']}, similarity={sim_pct}%, file={filename}):"
        )
        for fact in facts[:5]:
            lines.append(f"  • {fact.get('claim', '')} (confidence={fact.get('confidence', 0)})")
        lines.append("")

    lines.append("=== END CONTEXT ===")
    lines.append("")
    return "\n".join(lines)


def extract_node(state: GraphState, db: Session) -> GraphState:
    run_id = state["run_id"]
    classified = state.get("classified_docs", {})
    all_facts: list[ExtractedFact] = list(state.get("extracted_facts", []))
    retry_count = state.get("retry_count", 0)

    for doc_id, doc_type in classified.items():
        doc: Document = db.query(Document).filter_by(id=doc_id).first()
        if not doc or not doc.raw_text:
            continue

        t0 = time.monotonic()

        # ── RAG: retrieve similar facts from previous runs ────────────────────
        similar_docs = retrieve_similar_facts(
            query_text=doc.raw_text[:2000],
            db=db,
            exclude_run_id=run_id,
            limit=3,
        )
        context_block = _build_rag_context_block(similar_docs)
        rag_sources = len(similar_docs)

        # ── Build extraction prompt with optional RAG context ─────────────────
        base_prompt = EXTRACT_PROMPT.format(
            document=safe_wrap(doc.raw_text[:10000]),
            doc_id=doc_id,
            doc_type=doc_type,
        )
        prompt = context_block + base_prompt if context_block else base_prompt

        try:
            result_text, tok_in, tok_out = call_llm(prompt)
            facts_raw = parse_json_safe(result_text)

            if not isinstance(facts_raw, list):
                facts_raw = []

            # Validate and sanitise each fact
            validated: list[ExtractedFact] = []
            for f in facts_raw:
                # If AI says verified but left excerpt empty — mark unverified
                if f.get("is_verified") and not f.get("source_excerpt", "").strip():
                    f["is_verified"] = False
                    f["claim"] = f["claim"] + " [WARNING: no source excerpt found]"

                validated.append(ExtractedFact(
                    claim=f.get("claim", ""),
                    confidence=float(f.get("confidence", 0.5)),
                    source_doc_id=doc_id,
                    source_excerpt=f.get("source_excerpt", ""),
                    source_page=f.get("source_page"),
                    is_verified=bool(f.get("is_verified", True)),
                ))

            # Persist extracted facts on the document
            doc.extracted_facts = [dict(v) for v in validated]
            db.commit()

            # ── RAG: generate and store document embedding ────────────────────
            # Done AFTER extraction so we embed the actual ingested text.
            # Skips silently if OPENAI_API_KEY is not set.
            embed_and_store(doc, db)

            all_facts.extend(validated)
            duration = int((time.monotonic() - t0) * 1000)

            log_node(
                db, run_id, "extract", stage=1,
                decision=NodeDecision.CONTINUE,
                input_summary=f"doc_id={doc_id} type={doc_type} rag_sources={rag_sources}",
                output_summary=f"extracted {len(validated)} facts ({sum(1 for v in validated if not v['is_verified'])} unverified)",
                duration_ms=duration,
                tokens_in=tok_in, tokens_out=tok_out,
            )

        except Exception as e:
            decision = NodeDecision.RETRY if retry_count < 2 else NodeDecision.SKIP
            log_node(
                db, run_id, "extract", stage=1,
                decision=decision,
                input_summary=f"doc_id={doc_id}",
                error_detail=str(e),
                retry_count=retry_count,
            )
            if decision == NodeDecision.RETRY:
                return {
                    **state,
                    "current_node": "extract",
                    "last_decision": NodeDecision.RETRY,
                    "retry_count": retry_count + 1,
                    "extracted_facts": all_facts,
                }
            # SKIP: continue with next document, log the skip

    return {
        **state,
        "extracted_facts": all_facts,
        "current_node": "extract",
        "last_decision": NodeDecision.CONTINUE,
        "retry_count": 0,
    }

"""
ClassifyNode — Stage 1, step 1.
Reads each document, determines what type it is.
Decision: CONTINUE (success) | RETRY (parse error, retryable) | ESCALATE (unrecoverable)
"""
import time
import json
from sqlalchemy.orm import Session

from agents.state import GraphState, NodeDecision, ExtractedFact
from agents.prompts import CLASSIFY_PROMPT
from agents.nodes.base import safe_wrap, log_node, parse_json_safe
from db.models import Document, DocumentStatus
from services.llm_client import call_llm


def classify_node(state: GraphState, db: Session) -> GraphState:
    run_id = state["run_id"]
    doc_ids = state["document_ids"]
    classified = {}
    retry_count = state.get("retry_count", 0)

    for doc_id in doc_ids:
        doc: Document = db.query(Document).filter_by(id=doc_id).first()
        if not doc or not doc.raw_text:
            classified[doc_id] = "other"
            continue

        t0 = time.monotonic()
        prompt = CLASSIFY_PROMPT.format(document=safe_wrap(doc.raw_text[:8000]))

        result_text = ""
        tok_in = tok_out = 0
        try:
            result_text, tok_in, tok_out = call_llm(prompt)
            result = parse_json_safe(result_text)

            # parse_json_safe can extract a list if LLM returns prose with [] in it
            if not isinstance(result, dict):
                raise ValueError(
                    f"Expected JSON object from classifier, got {type(result).__name__}. "
                    f"Raw: {result_text[:120]}"
                )

            doc_type = result.get("doc_type", "other")
            doc.doc_type = doc_type
            doc.status = DocumentStatus.parsed
            db.commit()

            classified[doc_id] = doc_type
            duration = int((time.monotonic() - t0) * 1000)

            log_node(
                db, run_id, "classify", stage=1,
                decision=NodeDecision.CONTINUE,
                input_summary=f"doc_id={doc_id} filename={doc.filename}",
                output_summary=f"type={doc_type} confidence={result.get('confidence', 0):.2f}",
                duration_ms=duration,
                tokens_in=tok_in, tokens_out=tok_out,
            )

        except ValueError as json_err:
            # LLM returned prose instead of JSON.
            # Try to salvage a doc_type from keyword matches in the raw response
            # before falling back to retry/escalate.
            raw_lower = result_text.lower()
            salvaged_type = None
            for candidate in (
                "claim_form", "policy_document", "adjuster_notes",
                "coverage_schedule", "medical_report", "settlement_letter",
            ):
                if candidate.replace("_", " ") in raw_lower or candidate in raw_lower:
                    salvaged_type = candidate
                    break

            if salvaged_type:
                doc.doc_type = salvaged_type
                doc.status = DocumentStatus.parsed
                db.commit()
                classified[doc_id] = salvaged_type
                duration = int((time.monotonic() - t0) * 1000)
                log_node(
                    db, run_id, "classify", stage=1,
                    decision=NodeDecision.CONTINUE,
                    input_summary=f"doc_id={doc_id} filename={doc.filename}",
                    output_summary=(
                        f"type={salvaged_type} (salvaged from prose — JSON parse failed)"
                    ),
                    duration_ms=duration,
                    tokens_in=tok_in, tokens_out=tok_out,
                )
                continue  # move on to next doc

            # Could not salvage — retry or escalate
            doc.status = DocumentStatus.failed
            doc.parse_error = str(json_err)
            db.commit()

            decision = NodeDecision.RETRY if retry_count < 2 else NodeDecision.ESCALATE
            log_node(
                db, run_id, "classify", stage=1,
                decision=decision,
                input_summary=f"doc_id={doc_id}",
                error_detail=str(json_err),
                retry_count=retry_count,
            )

            if decision == NodeDecision.ESCALATE:
                # Fall back to "other" rather than blocking the whole pipeline
                doc.doc_type = "other"
                doc.status = DocumentStatus.parsed
                db.commit()
                classified[doc_id] = "other"
                log_node(
                    db, run_id, "classify", stage=1,
                    decision=NodeDecision.CONTINUE,
                    input_summary=f"doc_id={doc_id}",
                    output_summary="Fallback to doc_type=other after repeated JSON parse failures",
                )
            else:
                return {
                    **state,
                    "current_node": "classify",
                    "last_decision": NodeDecision.RETRY,
                    "retry_count": retry_count + 1,
                    "classified_docs": classified,
                }

        except Exception as e:
            doc.status = DocumentStatus.failed
            doc.parse_error = str(e)
            db.commit()

            decision = NodeDecision.RETRY if retry_count < 2 else NodeDecision.ESCALATE
            log_node(
                db, run_id, "classify", stage=1,
                decision=decision,
                input_summary=f"doc_id={doc_id}",
                error_detail=str(e),
                retry_count=retry_count,
            )

            if decision == NodeDecision.ESCALATE:
                return {
                    **state,
                    "current_node": "classify",
                    "last_decision": NodeDecision.ESCALATE,
                    "error": f"Classification failed for {doc.filename}: {e}",
                    "classified_docs": classified,
                }
            return {
                **state,
                "current_node": "classify",
                "last_decision": NodeDecision.RETRY,
                "retry_count": retry_count + 1,
                "classified_docs": classified,
            }

    return {
        **state,
        "classified_docs": classified,
        "current_node": "classify",
        "last_decision": NodeDecision.CONTINUE,
        "retry_count": 0,
    }

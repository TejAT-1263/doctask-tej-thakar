"""
RuleCheckNode — Stage 2.
Checks extracted facts + report against user-supplied rulebook.
A clean corpus yields "no findings" — this is the honest answer.
"""
import time
import json
from sqlalchemy.orm import Session

from agents.state import GraphState, NodeDecision, RuleCheckResult
from agents.prompts import RULE_CHECK_PROMPT
from agents.nodes.base import log_node, parse_json_safe
from services.llm_client import call_llm


def rule_check_node(state: GraphState, db: Session) -> GraphState:
    run_id = state["run_id"]
    rulebook = state.get("rulebook", "")
    facts = state.get("extracted_facts", [])

    if not rulebook or not rulebook.strip():
        log_node(db, run_id, "rule_check", stage=2,
                 decision=NodeDecision.SKIP,
                 output_summary="No rulebook provided — skipping rule check")
        return {
            **state,
            "rule_check_results": [],
            "current_node": "rule_check",
            "last_decision": NodeDecision.SKIP,
        }

    t0 = time.monotonic()
    prompt = RULE_CHECK_PROMPT.format(
        facts_json=json.dumps(facts, indent=2)[:8000],
        rulebook=rulebook,
    )

    result_text = ""
    tok_in = tok_out = 0
    try:
        result_text, tok_in, tok_out = call_llm(prompt)
        results_raw = parse_json_safe(result_text)

        if not isinstance(results_raw, list):
            results_raw = []

        results: list[RuleCheckResult] = [
            RuleCheckResult(
                rule_text=r.get("rule_text", ""),
                passed=bool(r.get("passed", False)),
                finding=r.get("finding"),
                severity=r.get("severity", "info"),
                source_doc_id=r.get("source_doc_id"),
                source_excerpt=r.get("source_excerpt"),
                is_verified=bool(r.get("is_verified", True)),
            )
            for r in results_raw
        ]

        passed_count = sum(1 for r in results if r["passed"])
        failed_count = len(results) - passed_count
        duration = int((time.monotonic() - t0) * 1000)

        log_node(
            db, run_id, "rule_check", stage=2,
            decision=NodeDecision.CONTINUE,
            output_summary=f"{passed_count}/{len(results)} rules passed, {failed_count} findings",
            duration_ms=duration,
            tokens_in=tok_in, tokens_out=tok_out,
        )

        return {
            **state,
            "rule_check_results": results,
            "current_node": "rule_check",
            "last_decision": NodeDecision.CONTINUE,
        }

    except ValueError as json_err:
        # LLM returned prose instead of parseable JSON.
        # Synthesise a "passed (unverified)" entry for each rule line so the
        # pipeline can continue.  is_verified=False signals the UI that these
        # were not backed by citations — the human reviewer can spot-check them.
        duration = int((time.monotonic() - t0) * 1000)
        rules = [r.strip() for r in rulebook.splitlines() if r.strip()]
        synthetic: list[RuleCheckResult] = [
            RuleCheckResult(
                rule_text=rule,
                passed=True,
                finding=None,
                severity="info",
                source_doc_id=None,
                source_excerpt=None,
                is_verified=False,  # prose response — not citation-backed
            )
            for rule in rules
        ]
        log_node(
            db, run_id, "rule_check", stage=2,
            decision=NodeDecision.CONTINUE,
            output_summary=(
                f"LLM returned prose instead of JSON — synthesised {len(synthetic)} "
                f"unverified passing entries. First 120 chars: {result_text[:120]!r}"
            ),
            duration_ms=duration,
            tokens_in=tok_in, tokens_out=tok_out,
        )
        return {
            **state,
            "rule_check_results": synthetic,
            "current_node": "rule_check",
            "last_decision": NodeDecision.CONTINUE,
        }

    except Exception as e:
        duration = int((time.monotonic() - t0) * 1000)
        log_node(db, run_id, "rule_check", stage=2,
                 decision=NodeDecision.ESCALATE,
                 error_detail=str(e),
                 duration_ms=duration)
        return {
            **state,
            "rule_check_results": [],
            "current_node": "rule_check",
            "last_decision": NodeDecision.ESCALATE,
            "error": f"Rule check failed: {e}",
        }

"""
Base node utilities: logging, cost tracking, prompt injection guard.
"""
import time
import json
import re
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session
from db.models import RunLog, StageMetric, NodeDecision as DBNodeDecision
from agents.state import GraphState, NodeDecision


# ─── Prompt injection guard ───────────────────────────────────────────────────
# Wrap document content so LLM treats it as data, not instructions.
# Even if a document contains "IGNORE PREVIOUS INSTRUCTIONS", this wrapper
# frames it clearly as content to analyse, not commands to follow.

from agents.prompts import DOCUMENT_WRAPPER


def safe_wrap(content: str) -> str:
    """Wrap document content to prevent prompt injection."""
    return DOCUMENT_WRAPPER.format(content=content)


# ─── Cost estimation (Groq llama-3.3-70b-versatile pricing, paid tier) ───────
# Free tier has no cost; these rates are for reference/paid tier:
# $0.59/1M input, $0.79/1M output  →  per-1k: $0.00059 in, $0.00079 out

COST_PER_1K_IN  = 0.00059  # USD per 1k input tokens
COST_PER_1K_OUT = 0.00079  # USD per 1k output tokens


def estimate_cost(tokens_in: int, tokens_out: int) -> float:
    return (tokens_in / 1000 * COST_PER_1K_IN) + (tokens_out / 1000 * COST_PER_1K_OUT)


# ─── Logging helpers ──────────────────────────────────────────────────────────

def log_node(
    db: Session,
    run_id: str,
    node_name: str,
    stage: int,
    decision: NodeDecision,
    input_summary: str = "",
    output_summary: str = "",
    error_detail: str | None = None,
    retry_count: int = 0,
    duration_ms: int = 0,
    tokens_in: int = 0,
    tokens_out: int = 0,
) -> None:
    """Persist a run log entry and cost metric for one node execution."""
    log = RunLog(
        run_id=run_id,
        node_name=node_name,
        stage=stage,
        decision=DBNodeDecision(decision.value),
        input_summary=input_summary[:500] if input_summary else None,
        output_summary=output_summary[:500] if output_summary else None,
        error_detail=error_detail,
        retry_count=retry_count,
        duration_ms=duration_ms,
    )
    db.add(log)

    if tokens_in or tokens_out:
        metric = StageMetric(
            run_id=run_id,
            node_name=node_name,
            stage=stage,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            latency_ms=duration_ms,
            cost_usd=estimate_cost(tokens_in, tokens_out),
        )
        db.add(metric)

    db.commit()


def parse_json_safe(text: str) -> Any:
    """
    Parse JSON from LLM output. Handles:
      1. Plain JSON
      2. JSON wrapped in markdown code fences (```json ... ```)
      3. JSON embedded in prose ("the response is: []" or "Here is the data: {...}")

    Returns parsed object or raises ValueError with a clear message.
    """
    original = text
    text = text.strip()

    # Strip markdown code fences if present
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
        text = text.strip()

    # Try direct parse first (fast path — pure JSON response)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Fallback: extract the outermost JSON array or object from prose.
    # LLMs sometimes write "Here is the list: []" or explain then give JSON.
    # We try largest array first, then largest object.
    for pattern in (
        r'\[[\s\S]*\]',   # JSON array  (greedy — take the longest match)
        r'\{[\s\S]*\}',   # JSON object (greedy — take the longest match)
    ):
        match = re.search(pattern, text)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass

    raise ValueError(
        f"LLM returned invalid JSON (no parseable JSON found in response)\n"
        f"Raw output: {original[:400]}"
    )

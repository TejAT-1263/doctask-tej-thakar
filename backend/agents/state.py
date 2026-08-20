"""
LangGraph state definition for the DocTask agentic system.
All fields are serialisable so checkpointing works transparently.
"""
from typing import TypedDict, Optional, List, Dict, Any
from enum import Enum


class NodeDecision(str, Enum):
    CONTINUE  = "continue"
    RETRY     = "retry"
    SKIP      = "skip"
    ESCALATE  = "escalate"


class ExtractedFact(TypedDict):
    claim: str
    confidence: float          # 0.0–1.0
    source_doc_id: str
    source_excerpt: str        # never empty — if blank, fact is marked unverified
    source_page: Optional[int]
    is_verified: bool


class Conflict(TypedDict):
    doc_a_id: str
    doc_b_id: str
    field: str
    value_a: str
    value_b: str
    description: str
    # ── Taxonomy additions ─────────────────────
    conflict_type: str   # FACTUAL | TEMPORAL | DEFINITIONAL | OMISSION
    severity: str        # low | medium | high


class RuleCheckResult(TypedDict):
    rule_text: str
    passed: bool
    finding: Optional[str]
    severity: str              # info | warning | critical
    source_doc_id: Optional[str]
    source_excerpt: Optional[str]
    is_verified: bool


# ── Creative addition TypedDicts ──────────────────────────────────────────────

class FraudSignal(TypedDict):
    """
    A pattern-based signal that warrants human review.
    NOT an accusation — a pointer to something that deserves attention.
    Generated deterministically from extracted facts; no LLM involved.
    """
    signal_id: str               # e.g. "TEMPORAL_PARADOX", "SHORT_POLICY_TENURE"
    title: str                   # short human-readable label
    description: str             # plain-English explanation
    confidence: str              # LOW | MEDIUM | HIGH
    evidence: str                # the values/text that triggered this signal
    source_doc_ids: List[str]    # which documents the evidence came from
    regulatory_ref: Optional[str]  # e.g. "IRDAI Health Regulations, 2016, Reg 8"


class TimelineEvent(TypedDict):
    """
    A single event extracted from the document set, placed on a timeline.
    Paradoxes (e.g., treatment before incident) are flagged explicitly.
    """
    date_iso: Optional[str]      # ISO 8601 if parseable, else None
    date_raw: str                # as it appeared in the source document
    event: str                   # what happened
    source_doc_id: str
    source_excerpt: str
    is_paradox: bool             # True if this event creates a temporal contradiction
    paradox_note: Optional[str]  # e.g. "Treatment (Mar 2) precedes incident (Mar 3)"


class DispositionRecommendation(TypedDict):
    """
    Structured recommendation generated after Stage 2.
    The human adjuster makes the final call — this is decision support, not decision.
    """
    disposition: str             # APPROVE | DENY | REQUEST_MORE_INFO
    confidence: str              # HIGH | MEDIUM | LOW
    rationale: str               # paragraph with cited findings
    supporting_findings: List[str]   # findings that support the disposition
    blocking_issues: List[str]       # issues that must be resolved before approval


class ReportChange(TypedDict):
    """
    A single change made to the report during Stage 3 (watcher).
    Proves what changed, what stayed the same, and why.
    """
    section: str
    change_type: str             # update | addition | conflict_flag
    old_content: Optional[str]
    new_content: str
    reason: str
    source_doc: str              # filename of the document that triggered the change


class GraphState(TypedDict):
    # ── Identity ──────────────────────────────
    run_id: str

    # ── Input ─────────────────────────────────
    document_ids: List[str]      # DB Document IDs for this run
    rulebook: Optional[str]      # user-supplied rules / checklist

    # ── Stage 1 outputs ───────────────────────
    classified_docs: Dict[str, str]          # doc_id → doc_type
    extracted_facts: List[ExtractedFact]
    conflicts: List[Conflict]
    report_html: Optional[str]               # grounded report

    # ── Creative additions: Stage 1 ───────────
    fraud_signals: List[FraudSignal]         # pattern-based signals (no LLM)
    timeline_events: List[TimelineEvent]     # chronological event reconstruction

    # ── Stage 2 outputs ───────────────────────
    rule_check_results: List[RuleCheckResult]
    findings_html: Optional[str]

    # ── Creative additions: Stage 2 ───────────
    disposition_recommendation: Optional[DispositionRecommendation]

    # ── Control flow ──────────────────────────
    current_node: str
    current_stage: int
    last_decision: Optional[NodeDecision]
    retry_count: int
    error: Optional[str]
    hitl_pending: bool           # True = graph is paused at HITL gate

    # ── Stage 3 (watcher) ─────────────────────
    new_doc_ids: List[str]       # docs that arrived after initial run
    affected_sections: List[str] # which parts of the report to update
    report_diff: Optional[List[ReportChange]]  # provenance diff for Stage 3 updates
    pending_stage3_addendum: Optional[str]     # staged HTML — NOT in report_html yet;
                                               # committed on HITL approve, discarded on reject

    # ── Cost tracking ─────────────────────────
    total_tokens_in: int
    total_tokens_out: int
    total_cost_usd: float

"""
LangGraph workflow definition for the DocTask agentic system.

Stage 1: classify → extract → fraud_signal → reconcile → hitl_gate_1
Stage 2: rule_check → hitl_gate_2 → recommend
Stage 3: watcher (triggered by new document arrivals)

Creative additions wired in:
  - fraud_signal: rule-based India-specific signal detection (after extract)
  - recommend: LLM-based disposition recommendation (after hitl_gate_2)

Checkpointing: every node saves state via PostgresSaver before returning.
Kill the process, restart — it resumes from the last completed node.
"""
from functools import partial
from typing import Literal

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
try:
    from langgraph.checkpoint.sqlite import SqliteSaver as _SqliteSaver
    _HAS_SQLITE_SAVER = True
except ImportError:
    _HAS_SQLITE_SAVER = False

from agents.state import GraphState, NodeDecision
from agents.nodes.classify import classify_node
from agents.nodes.extract import extract_node
from agents.nodes.fraud_signal import fraud_signal_node
from agents.nodes.reconcile import reconcile_node
from agents.nodes.rule_check import rule_check_node
from agents.nodes.hitl_gate import hitl_gate_node
from agents.nodes.recommend import recommend_node
from agents.nodes.watcher import watcher_node
from db.database import SessionLocal


# ─── Node wrappers (inject DB session) ───────────────────────────────────────

def _with_db(fn, *args, **kwargs):
    """Run a node function with a fresh DB session, always committing or rolling back."""
    db = SessionLocal()
    try:
        result = fn(*args, db=db, **kwargs)
        return result
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def classify_node_wrapper(state: GraphState) -> GraphState:
    return _with_db(classify_node, state)

def extract_node_wrapper(state: GraphState) -> GraphState:
    return _with_db(extract_node, state)

def fraud_signal_node_wrapper(state: GraphState) -> GraphState:
    return _with_db(fraud_signal_node, state)

def reconcile_node_wrapper(state: GraphState) -> GraphState:
    return _with_db(reconcile_node, state)

def rule_check_node_wrapper(state: GraphState) -> GraphState:
    return _with_db(rule_check_node, state)

def hitl_gate_1_wrapper(state: GraphState) -> GraphState:
    return _with_db(hitl_gate_node, state, stage=1)

def hitl_gate_2_wrapper(state: GraphState) -> GraphState:
    return _with_db(hitl_gate_node, state, stage=2)

def recommend_node_wrapper(state: GraphState) -> GraphState:
    return _with_db(recommend_node, state)

def watcher_node_wrapper(state: GraphState) -> GraphState:
    return _with_db(watcher_node, state)


# ─── Conditional edge functions ───────────────────────────────────────────────

def classify_router(state: GraphState) -> Literal["extract", "classify", END]:
    decision = state.get("last_decision")
    if decision == NodeDecision.RETRY:
        return "classify"       # retry this node
    if decision == NodeDecision.ESCALATE:
        return END              # unrecoverable — stop
    return "extract"            # CONTINUE → next node


def extract_router(state: GraphState) -> Literal["fraud_signal", "extract"]:
    decision = state.get("last_decision")
    if decision == NodeDecision.RETRY:
        return "extract"        # retry
    return "fraud_signal"       # CONTINUE or SKIP → fraud signal check


def fraud_signal_router(state: GraphState) -> Literal["reconcile"]:
    # fraud_signal never blocks the pipeline — always proceed to reconcile
    return "reconcile"


def reconcile_router(state: GraphState) -> Literal["hitl_gate_1", END]:
    decision = state.get("last_decision")
    if decision == NodeDecision.ESCALATE:
        return END
    return "hitl_gate_1"


def hitl_gate_1_router(state: GraphState) -> Literal["rule_check", END]:
    """
    This gate PAUSES the graph.
    The FastAPI /resume endpoint sets hitl_pending=False and calls graph.invoke() again.
    Until then, the graph returns to END (checkpointed at this node).
    """
    if state.get("hitl_pending", True):
        return END              # paused — checkpoint saved, resume later
    return "rule_check"


def rule_check_router(state: GraphState) -> Literal["hitl_gate_2", END]:
    decision = state.get("last_decision")
    if decision == NodeDecision.ESCALATE:
        return END
    return "hitl_gate_2"


def hitl_gate_2_router(state: GraphState) -> Literal["recommend", END]:
    if state.get("hitl_pending", True):
        return END
    return "recommend"


def recommend_router(state: GraphState) -> Literal["watcher"]:
    # recommend never blocks the pipeline — always proceed to watcher
    return "watcher"


# ─── Build the graph ──────────────────────────────────────────────────────────

def build_graph(checkpointer) -> StateGraph:
    builder = StateGraph(GraphState)

    # Add nodes
    builder.add_node("classify",      classify_node_wrapper)
    builder.add_node("extract",       extract_node_wrapper)
    builder.add_node("fraud_signal",  fraud_signal_node_wrapper)
    builder.add_node("reconcile",     reconcile_node_wrapper)
    builder.add_node("hitl_gate_1",   hitl_gate_1_wrapper)
    builder.add_node("rule_check",    rule_check_node_wrapper)
    builder.add_node("hitl_gate_2",   hitl_gate_2_wrapper)
    builder.add_node("recommend",     recommend_node_wrapper)
    builder.add_node("watcher",       watcher_node_wrapper)

    # Entry point
    builder.set_entry_point("classify")

    # Edges with conditional routing
    builder.add_conditional_edges("classify",      classify_router)
    builder.add_conditional_edges("extract",       extract_router)
    builder.add_conditional_edges("fraud_signal",  fraud_signal_router)
    builder.add_conditional_edges("reconcile",     reconcile_router)
    builder.add_conditional_edges("hitl_gate_1",   hitl_gate_1_router)
    builder.add_conditional_edges("rule_check",    rule_check_router)
    builder.add_conditional_edges("hitl_gate_2",   hitl_gate_2_router)
    builder.add_conditional_edges("recommend",     recommend_router)

    # Watcher → END (or loops back for more new docs)
    builder.add_edge("watcher", END)

    return builder.compile(checkpointer=checkpointer)


# ─── Singleton graph instance ─────────────────────────────────────────────────

_graph_instance = None

def get_graph() -> StateGraph:
    global _graph_instance
    if _graph_instance is None:
        from config import get_settings
        settings = get_settings()
        checkpointer = None

        # 1. Try PostgreSQL (production)
        if settings.database_url.startswith("postgresql"):
            try:
                from langgraph.checkpoint.postgres import PostgresSaver
                checkpointer = PostgresSaver.from_conn_string(settings.database_url)
                checkpointer.setup()
            except Exception:
                checkpointer = None

        # 2. Try SQLite (dev/demo — persists across hot-reloads unlike MemorySaver)
        if checkpointer is None and _HAS_SQLITE_SAVER:
            try:
                import os, sqlite3
                db_dir = os.path.dirname(os.path.abspath(__file__))
                sqlite_path = os.path.join(db_dir, "..", "doctask_checkpoints.db")
                # Use direct connection — from_conn_string is a context manager
                # and cannot be used for a long-lived singleton without `with`.
                conn = sqlite3.connect(str(sqlite_path), check_same_thread=False)
                checkpointer = _SqliteSaver(conn)
            except Exception:
                checkpointer = None

        # 3. Fall back to MemorySaver (state is lost on restart — last resort only)
        if checkpointer is None:
            import warnings
            warnings.warn(
                "Using MemorySaver — LangGraph state will be lost on server restart. "
                "Install langgraph-checkpoint-sqlite for persistence.",
                stacklevel=2,
            )
            checkpointer = MemorySaver()

        _graph_instance = build_graph(checkpointer)
    return _graph_instance


def initial_state(run_id: str, document_ids: list[str], rulebook: str = "") -> GraphState:
    """Create a fresh starting state for a new run."""
    return GraphState(
        run_id=run_id,
        document_ids=document_ids,
        rulebook=rulebook,
        classified_docs={},
        extracted_facts=[],
        conflicts=[],
        report_html=None,
        # Creative additions
        fraud_signals=[],
        timeline_events=[],
        disposition_recommendation=None,
        report_diff=None,
        # Stage 2
        rule_check_results=[],
        findings_html=None,
        # Control flow
        current_node="",
        current_stage=1,
        last_decision=None,
        retry_count=0,
        error=None,
        hitl_pending=False,
        # Stage 3
        new_doc_ids=[],
        affected_sections=[],
        pending_stage3_addendum=None,
        # Cost
        total_tokens_in=0,
        total_tokens_out=0,
        total_cost_usd=0.0,
    )

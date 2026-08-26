"""
DocTask FastAPI application.
One command: uvicorn main:app --reload
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from db.database import init_db
from api.runs import router as runs_router
from api.review import router as review_router
from api.search import router as search_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle (replaces deprecated @app.on_event)."""
    import threading
    from db.database import SessionLocal
    from db.models import Run, RunStatus
    from api.runs import _resume_agent

    init_db()

    # Requirement: "Kill the process in the middle of a run and start it again.
    # It continues from where it left off, and no finished work is lost."
    #
    # Runs in 'running' state at shutdown lost their background task.
    # LangGraph's SQLite checkpointer preserved every completed node's output.
    # Re-launch _resume_agent in a thread for each orphaned run — it calls
    # graph.invoke(None, config) which resumes from the last checkpoint.
    with SessionLocal() as db:
        orphaned = db.query(Run).filter(Run.status == RunStatus.running).all()
        orphaned_ids = [r.id for r in orphaned]

    for run_id in orphaned_ids:
        t = threading.Thread(target=_resume_agent, args=(run_id,), daemon=True)
        t.start()

    yield
    # Nothing to clean up on shutdown


app = FastAPI(
    title="DocTask — Agentic Document Analysis System",
    description=(
        "Analyses a pile of related documents end-to-end: "
        "classifies, extracts facts, detects conflicts, checks rules, "
        "and gates every output through human review before committing."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(runs_router)
app.include_router(review_router)
app.include_router(search_router)


@app.get("/health")
def health():
    return {"status": "ok", "service": "doctask"}


@app.get("/")
def root():
    return {
        "service": "DocTask",
        "docs": "/docs",
        "openapi": "/openapi.json",
        "mcp": "Run `python -m mcp_server.server` for the MCP interface (stdio transport)",
    }

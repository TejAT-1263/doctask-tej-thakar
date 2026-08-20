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
    init_db()
    yield
    # Nothing to clean up on shutdown yet


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

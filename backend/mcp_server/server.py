"""
DocTask MCP Server — stdio transport
=====================================
Exposes the DocTask HITL pipeline as 8 MCP tools so that an orchestrating
agent (Claude, GPT-4o, etc.) can drive a full document-analysis run without
a browser.

Run:
    python -m mcp_server.server

Requires the FastAPI backend to be running on BACKEND_URL (default: http://localhost:8000).

8 Tools
-------
1.  start_run           — Upload documents and start an analysis run
2.  get_run_status      — Check whether a run is running / paused / complete
3.  list_review_items   — List pending HITL review items (filter by stage / status)
4.  approve_item        — Approve one review item
5.  reject_item         — Reject one review item with an optional note
6.  get_review_summary  — How many items are pending / approved / rejected, by stage
7.  resume_run          — Resume a paused run (only once all items are decided)
8.  get_run_report      — Retrieve the final HTML report for a completed run
"""

import json
import os
import sys
from typing import Any

import httpx

# ── MCP SDK ────────────────────────────────────────────────────────────────────
# The `mcp` package ships with the Anthropic Python SDK extras.
# Install with: pip install "mcp[cli]"
try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import Tool, TextContent
except ImportError:
    print(
        "MCP SDK not found. Install with:\n  pip install \"mcp[cli]\"",
        file=sys.stderr,
    )
    sys.exit(1)

BACKEND_URL = os.environ.get("DOCTASK_BACKEND_URL", "http://localhost:8000")

server = Server("doctask")


def _client() -> httpx.Client:
    return httpx.Client(base_url=BACKEND_URL, timeout=60.0)


def _ok(data: Any) -> list[TextContent]:
    return [TextContent(type="text", text=json.dumps(data, indent=2))]


def _err(msg: str) -> list[TextContent]:
    return [TextContent(type="text", text=json.dumps({"error": msg}))]


# ── Tool definitions ───────────────────────────────────────────────────────────

@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="start_run",
            description=(
                "Upload a set of documents and start a new DocTask analysis run. "
                "Returns a run_id to poll with get_run_status. "
                "The run will pause at HITL gates; check get_run_status to know when."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "documents": {
                        "type": "array",
                        "description": "List of documents to analyse.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "filename": {"type": "string", "description": "Document filename (e.g. 'claim_form.pdf')"},
                                "content": {"type": "string", "description": "Full text content of the document"},
                                "doc_type": {"type": "string", "description": "Optional hint: 'claim_form', 'adjuster_notes', 'policy_schedule', 'medical_report', 'other'"},
                            },
                            "required": ["filename", "content"],
                        },
                    },
                    "rulebook": {
                        "type": "string",
                        "description": "Optional plain-text rulebook for the rule-check stage.",
                    },
                    "run_id": {
                        "type": "string",
                        "description": "Optional custom run ID. If omitted, one is generated.",
                    },
                },
                "required": ["documents"],
            },
        ),
        Tool(
            name="get_run_status",
            description=(
                "Check the current status of a run. "
                "Returns: running | paused_hitl_stage1 | paused_hitl_stage2 | completed | failed. "
                "When paused, call list_review_items to see what needs human review."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "run_id": {"type": "string", "description": "Run ID returned by start_run"},
                },
                "required": ["run_id"],
            },
        ),
        Tool(
            name="list_review_items",
            description=(
                "List HITL review items for a run. "
                "Filter by stage (1 = conflict review, 2 = rule-check review) and/or status (pending | approved | rejected). "
                "Returns items with their body (the conflict or rule-fail description) and current status."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "run_id": {"type": "string"},
                    "stage": {"type": "integer", "enum": [1, 2], "description": "Filter by HITL stage (optional)"},
                    "status": {"type": "string", "enum": ["pending", "approved", "rejected"], "description": "Filter by item status (optional)"},
                },
                "required": ["run_id"],
            },
        ),
        Tool(
            name="approve_item",
            description=(
                "Approve a single HITL review item. "
                "Approving one item never affects other items in the same run. "
                "Once all items are approved or rejected, call resume_run."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "run_id": {"type": "string"},
                    "item_id": {"type": "string", "description": "Item ID from list_review_items"},
                    "reviewer_note": {"type": "string", "description": "Optional reviewer note (logged for audit)"},
                },
                "required": ["run_id", "item_id"],
            },
        ),
        Tool(
            name="reject_item",
            description=(
                "Reject a single HITL review item with an optional note. "
                "Rejecting one item never discards other items in the same run. "
                "Once all items are decided, call resume_run."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "run_id": {"type": "string"},
                    "item_id": {"type": "string", "description": "Item ID from list_review_items"},
                    "reviewer_note": {"type": "string", "description": "Required when rejecting — explain what was wrong"},
                },
                "required": ["run_id", "item_id"],
            },
        ),
        Tool(
            name="get_review_summary",
            description=(
                "Get a count of pending / approved / rejected items by stage. "
                "all_decided=true means resume_run can be called."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "run_id": {"type": "string"},
                },
                "required": ["run_id"],
            },
        ),
        Tool(
            name="resume_run",
            description=(
                "Resume a run that is paused at a HITL gate. "
                "Only works when all review items are decided (all_decided=true from get_review_summary). "
                "The run continues from where it paused."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "run_id": {"type": "string"},
                },
                "required": ["run_id"],
            },
        ),
        Tool(
            name="get_run_report",
            description=(
                "Retrieve the final HTML report for a completed run. "
                "Only available when get_run_status returns 'completed'. "
                "Returns the full grounded report with citations, conflict taxonomy, "
                "fraud signals, disposition recommendation, and adjuster sign-off."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "run_id": {"type": "string"},
                },
                "required": ["run_id"],
            },
        ),
    ]


# ── Tool call handler ──────────────────────────────────────────────────────────

@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
        with _client() as client:
            if name == "start_run":
                return await _start_run(client, arguments)
            elif name == "get_run_status":
                return await _get_run_status(client, arguments)
            elif name == "list_review_items":
                return await _list_review_items(client, arguments)
            elif name == "approve_item":
                return await _approve_item(client, arguments)
            elif name == "reject_item":
                return await _reject_item(client, arguments)
            elif name == "get_review_summary":
                return await _get_review_summary(client, arguments)
            elif name == "resume_run":
                return await _resume_run(client, arguments)
            elif name == "get_run_report":
                return await _get_run_report(client, arguments)
            else:
                return _err(f"Unknown tool: {name}")
    except httpx.ConnectError:
        return _err(f"Cannot connect to DocTask backend at {BACKEND_URL}. Is it running?")
    except Exception as e:
        return _err(f"Unexpected error: {e}")


# ── Individual tool implementations ────────────────────────────────────────────

async def _start_run(client: httpx.Client, args: dict) -> list[TextContent]:
    # The backend accepts multipart/form-data: files list + optional rulebook text field.
    documents = args["documents"]
    rulebook = args.get("rulebook", "")

    # Build multipart form: each document becomes an UploadFile entry.
    files = []
    for doc in documents:
        filename = doc.get("filename", "document.txt")
        content = doc.get("content", "")
        # Prepend doc_type as a comment if provided, so the LLM has context.
        doc_type = doc.get("doc_type")
        if doc_type:
            content = f"[Document type: {doc_type}]\n\n{content}"
        files.append(("files", (filename, content.encode(), "text/plain")))

    data = {}
    if rulebook:
        data["rulebook"] = rulebook

    resp = client.post("/api/runs", files=files, data=data)
    if resp.status_code not in (200, 201):
        return _err(f"start_run failed: HTTP {resp.status_code} — {resp.text[:400]}")
    return _ok(resp.json())


async def _get_run_status(client: httpx.Client, args: dict) -> list[TextContent]:
    run_id = args["run_id"]
    resp = client.get(f"/api/runs/{run_id}")
    if resp.status_code == 404:
        return _err(f"Run not found: {run_id}")
    if not resp.is_success:
        return _err(f"get_run_status failed: HTTP {resp.status_code}")
    return _ok(resp.json())


async def _list_review_items(client: httpx.Client, args: dict) -> list[TextContent]:
    run_id = args["run_id"]
    params = {}
    if "stage" in args:
        params["stage"] = args["stage"]
    if "status" in args:
        params["status"] = args["status"]

    resp = client.get(f"/api/runs/{run_id}/review", params=params)
    if not resp.is_success:
        return _err(f"list_review_items failed: HTTP {resp.status_code} — {resp.text[:200]}")
    return _ok(resp.json())


async def _approve_item(client: httpx.Client, args: dict) -> list[TextContent]:
    run_id = args["run_id"]
    item_id = args["item_id"]
    body = {"reviewer_note": args.get("reviewer_note")}

    resp = client.post(f"/api/runs/{run_id}/review/{item_id}/approve", json=body)
    if not resp.is_success:
        return _err(f"approve_item failed: HTTP {resp.status_code} — {resp.text[:200]}")
    return _ok(resp.json())


async def _reject_item(client: httpx.Client, args: dict) -> list[TextContent]:
    run_id = args["run_id"]
    item_id = args["item_id"]
    body = {"reviewer_note": args.get("reviewer_note")}

    resp = client.post(f"/api/runs/{run_id}/review/{item_id}/reject", json=body)
    if not resp.is_success:
        return _err(f"reject_item failed: HTTP {resp.status_code} — {resp.text[:200]}")
    return _ok(resp.json())


async def _get_review_summary(client: httpx.Client, args: dict) -> list[TextContent]:
    run_id = args["run_id"]
    resp = client.get(f"/api/runs/{run_id}/review/summary")
    if not resp.is_success:
        return _err(f"get_review_summary failed: HTTP {resp.status_code}")
    return _ok(resp.json())


async def _resume_run(client: httpx.Client, args: dict) -> list[TextContent]:
    run_id = args["run_id"]

    # Check all items are decided before allowing resume
    summary_resp = client.get(f"/api/runs/{run_id}/review/summary")
    if summary_resp.is_success:
        summary = summary_resp.json()
        if not summary.get("all_decided", False):
            pending = sum(
                s.get("pending", 0) for s in summary.get("by_stage", [])
            )
            return _err(
                f"Cannot resume: {pending} review item(s) still pending. "
                f"Call approve_item or reject_item for each pending item first."
            )

    # The resume endpoint requires {"stage": int} in the request body.
    # Auto-detect current_stage from run status.
    stage = 1  # fallback
    status_resp = client.get(f"/api/runs/{run_id}")
    if status_resp.is_success:
        stage = status_resp.json().get("current_stage", 1)

    resp = client.post(f"/api/runs/{run_id}/resume", json={"stage": stage})
    if not resp.is_success:
        return _err(f"resume_run failed: HTTP {resp.status_code} — {resp.text[:200]}")
    return _ok(resp.json())


async def _get_run_report(client: httpx.Client, args: dict) -> list[TextContent]:
    run_id = args["run_id"]
    resp = client.get(f"/api/runs/{run_id}/report")
    if resp.status_code == 404:
        return _err(
            f"Report not found for run {run_id}. "
            "Is the run complete? Check get_run_status first."
        )
    if not resp.is_success:
        return _err(f"get_run_report failed: HTTP {resp.status_code}")
    # Report may be HTML or JSON
    ct = resp.headers.get("content-type", "")
    if "json" in ct:
        return _ok(resp.json())
    return [TextContent(type="text", text=resp.text)]


# ── Entry point ────────────────────────────────────────────────────────────────

async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())

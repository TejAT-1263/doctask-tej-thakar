# doctask-tej-thakar

**Domain: Insurance Claims**  
Agentic document analysis system for insurance claim processing — built for the SuperDocs engineering task.

---

## What it does

Uploads a set of claim documents (PDF, DOCX, TXT), runs a 9-node LangGraph pipeline to classify, extract facts, detect fraud signals, reconcile conflicts, check against a rulebook, and generate a structured disposition recommendation — with two human-in-the-loop review gates before the final output commits. Survives process kills via PostgresSaver (production) or SqliteSaver (dev) checkpointing. Exposes a full MCP server so any agent can drive the entire flow — including the HITL gate — programmatically.

**Pipeline stages:**

```
classify → extract → fraud_signal → reconcile → hitl_gate_1 → rule_check → hitl_gate_2 → recommend → watcher
```

Every node writes a `RunLog` entry with its decision (CONTINUE / RETRY / SKIP / ESCALATE). Cost is tracked per node in `StageMetric`.

---

## One-command setup

**Prerequisites:** Docker, Docker Compose, a SuperDocs API key (redeem `BUILDER26` at use.superdocs.app → Settings → Billing)

```bash
git clone https://github.com/tej-thakar/doctask-tej-thakar
cd doctask-tej-thakar
cp .env.example .env
# Edit .env — add SUPERDOCS_API_KEY and GROQ_API_KEY
docker-compose up --build
```

Open `http://localhost:3000` to use the review UI.

**Local dev (no Docker):**

```bash
make setup        # installs all Python deps (required before anything else)
make test         # runs all 44 tests — no live API key needed
make dev          # starts FastAPI on :8000
make mcp          # starts MCP stdio server
```

`make test` runs `make setup` automatically, so you can also just run `make test` directly on a fresh checkout.

---

## Architecture

```
┌─────────────────────────────────────┐
│          React Review UI            │
│  (Upload · Review · Analysis · Dev) │
└──────────────┬──────────────────────┘
               │ REST API
┌──────────────▼──────────────────────┐
│           FastAPI Backend           │
│  /api/runs  /api/review  /api/cost  │
└──────┬─────────────────┬────────────┘
       │ LangGraph       │ SQLAlchemy
┌──────▼──────┐   ┌──────▼──────────┐
│  StateGraph  │   │   PostgreSQL    │
│ PostgresSaver│   │  + pgvector     │
│  9 nodes     │   │  6 tables       │
└─────────────┘   └─────────────────┘
       │
┌──────▼──────────────────────────────┐
│        MCP Server (stdio transport) │
│  8 tools — machine-callable HITL   │
└─────────────────────────────────────┘
```

Pipeline: `classify → extract → fraud_signal → reconcile → hitl_gate_1 → rule_check → hitl_gate_2 → recommend → watcher`

---

## Running tests

No live API key required — all LLM calls are mocked.

```bash
make test           # installs deps if needed, then runs all 44 tests
```

Or manually:

```bash
python3 -m pip install --user -r backend/requirements.txt
python3 -m pytest backend/tests/ -q
```

Note: the `--user` flag installs to `~/Library/Python/3.x/…` (Mac) or `~/.local/lib/…` (Linux), which is always writable without `sudo`. The `.venv` directory is gitignored — do not use `.venv/bin/python`.

Test files:

| File | What it covers |
|---|---|
| `test_checkpoint.py` | classify→extract pipeline, kill-and-resume simulation, Stage 3 gate correctness |
| `test_concurrent_runs.py` | two runs never share state |
| `test_injection_defense.py` | adversarial doc content treated as data |
| `test_hitl_gate.py` | gate pauses run; approve/reject one item doesn't affect others |
| `test_rag_pipeline.py` | embedding storage, similarity search, graceful zero-vector degradation |

---

## API quick reference

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/runs` | Upload docs, start agent |
| `GET` | `/api/runs/{id}` | Status + pending review count |
| `GET` | `/api/runs/{id}/review` | List review items |
| `POST` | `/api/runs/{id}/review/{item_id}/approve` | Approve one item |
| `POST` | `/api/runs/{id}/review/{item_id}/reject` | Reject one item (note required) |
| `POST` | `/api/runs/{id}/resume` | Resume after all items decided |
| `POST` | `/api/runs/{id}/watch` | Stage 3 — add new documents |
| `GET` | `/api/runs/{id}/report` | Final HTML report |
| `GET` | `/api/runs/{id}/cost` | Cost breakdown by node |
| `GET` | `/api/runs/{id}/logs` | Execution log |

---

## MCP server

Runs as an stdio MCP server. To connect, run it as a subprocess and wire it to your MCP client's stdio config (e.g. Claude Desktop). Eight tools:

`upload_documents` · `get_run_status` · `get_pending_review_items` · `approve_item` · `reject_item` · `resume_run` · `get_report` · `get_run_cost`

---

## Environment variables

| Variable | Description |
|---|---|
| `SUPERDOCS_API_KEY` | From use.superdocs.app (use promo `BUILDER26`) |
| `GROQ_API_KEY` | Groq API key — model `llama-3.3-70b-versatile` |
| `OPENAI_API_KEY` | Optional — only needed for RAG embeddings (text-embedding-3-small) |
| `DATABASE_URL` | PostgreSQL connection string |
| `SECRET_KEY` | FastAPI session secret |
| `VITE_API_BASE` | Frontend API base URL (default `http://localhost:8000`) |

---

## Assumptions

See `PROGRESS.md` for build decisions and deviations from the spec.

## Known bugs / SuperDocs API notes

See `BUGS.md`.

"""
Test: RAG pipeline (embedding generation, storage, retrieval, context injection).

Tests in this file:
1. generate_embedding() returns a zero vector when OPENAI_API_KEY is not set
2. generate_embedding() calls the OpenAI client when key is set
3. embed_and_store() skips storage when the result is a zero vector
4. embed_and_store() writes to doc.embedding when embedding is non-zero
5. search functions return [] when generate_embedding() produces a zero vector
6. _build_rag_context_block() returns an empty string when similar_docs is empty
7. _build_rag_context_block() injects similar facts into the context string
8. extract_node injects a context block when retrieve_similar_facts returns data
9. extract_node calls embed_and_store after successful extraction

No live API key needed — generate_embedding() is mocked throughout.
"""
import uuid
import pytest
from unittest.mock import patch, MagicMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db.models import Base, Document, Run, RunStatus


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(scope="function")
def db():
    # Use /tmp to avoid disk I/O errors on FUSE-mounted test environments
    engine = create_engine(
        "sqlite:////tmp/doctask_test_rag.db",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


@pytest.fixture
def sample_doc(db):
    run_id = str(uuid.uuid4())
    run = Run(
        id=run_id, status=RunStatus.running, domain="insurance_claims",
        rulebook="", current_stage=1, current_node="extract",
        checkpoint_thread_id=run_id, total_cost_usd=0.0,
    )
    db.add(run)
    doc = Document(
        id=str(uuid.uuid4()), run_id=run_id,
        filename="claim.txt", raw_text="Claim amount: $45,000. Policy: POL-789.",
        doc_type="claim_form",
    )
    db.add(doc)
    db.commit()
    return doc, run_id


_FAKE_VECTOR = [0.1] * 1536
_ZERO_VECTOR = [0.0] * 1536


# ─── 1. generate_embedding: no key → zero vector ──────────────────────────────

def test_generate_embedding_no_key_returns_zero():
    from services.embeddings import generate_embedding

    with patch("services.embeddings.get_settings") as mock_settings:
        mock_settings.return_value = MagicMock(openai_api_key="")
        result = generate_embedding("some text")

    assert result == _ZERO_VECTOR
    assert len(result) == 1536


# ─── 2. generate_embedding: key set → calls OpenAI ───────────────────────────

def test_generate_embedding_calls_openai_when_key_set():
    from services.embeddings import generate_embedding

    mock_response = MagicMock()
    mock_response.data = [MagicMock(embedding=_FAKE_VECTOR)]

    with patch("services.embeddings.get_settings") as mock_settings, \
         patch("openai.OpenAI") as mock_openai_cls:

        mock_settings.return_value = MagicMock(openai_api_key="sk-test")
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.embeddings.create.return_value = mock_response

        result = generate_embedding("insurance claim text")

    assert result == _FAKE_VECTOR
    mock_client.embeddings.create.assert_called_once()
    call_kwargs = mock_client.embeddings.create.call_args
    assert call_kwargs[1]["model"] == "text-embedding-3-small"


# ─── 3. embed_and_store: zero vector → does not touch doc.embedding ──────────

def test_embed_and_store_skips_on_zero_vector(sample_doc, db):
    from services.embeddings import embed_and_store

    doc, _ = sample_doc
    # Baseline: embedding starts as None
    assert doc.embedding is None

    with patch("services.embeddings.generate_embedding", return_value=_ZERO_VECTOR):
        embed_and_store(doc, db)

    # embed_and_store should have returned early — embedding stays None in memory
    assert doc.embedding is None


# ─── 4. embed_and_store: non-zero vector → sets doc.embedding in memory ───────

def test_embed_and_store_writes_embedding(sample_doc, db):
    """
    Verifies embed_and_store() assigns the embedding to the in-memory object.
    We check in-memory state (not a DB round-trip) because SQLite does not natively
    understand pgvector's Vector(1536) type — that round-trip is an integration test
    concern against real Postgres, not a unit test concern.
    """
    from services.embeddings import embed_and_store

    doc, _ = sample_doc

    with patch("services.embeddings.generate_embedding", return_value=_FAKE_VECTOR):
        embed_and_store(doc, db)

    # Check the in-memory assignment — do NOT refresh from SQLite
    # Use pytest.approx to handle float precision differences from pgvector round-trip
    import pytest
    assert list(doc.embedding) == pytest.approx(list(_FAKE_VECTOR))


# ─── 5. search functions: zero vector → return [] ─────────────────────────────

def test_search_by_text_returns_empty_on_zero_vector(db):
    from services.embeddings import search_by_text

    with patch("services.embeddings.generate_embedding", return_value=_ZERO_VECTOR):
        result = search_by_text("find me a claim", db)

    assert result == []


def test_search_similar_to_doc_returns_empty_when_no_embedding(sample_doc, db):
    from services.embeddings import search_similar_to_doc

    doc, _ = sample_doc
    # doc has no embedding set — should return []
    result = search_similar_to_doc(doc.id, db)
    assert result == []


def test_retrieve_similar_facts_returns_empty_on_zero_vector(db):
    from services.embeddings import retrieve_similar_facts

    with patch("services.embeddings.generate_embedding", return_value=_ZERO_VECTOR):
        result = retrieve_similar_facts(
            "claim for fire damage",
            db,
            exclude_run_id=str(uuid.uuid4()),
        )

    assert result == []


# ─── 6. _build_rag_context_block: empty list → empty string ──────────────────

def test_build_rag_context_block_empty():
    from agents.nodes.extract import _build_rag_context_block

    result = _build_rag_context_block([])
    assert result == ""


# ─── 7. _build_rag_context_block: injects similar facts ──────────────────────

def test_build_rag_context_block_injects_facts():
    from agents.nodes.extract import _build_rag_context_block

    similar_docs = [
        {
            "doc_id": "abc",
            "doc_type": "claim_form",
            "filename": "past_claim.txt",
            "similarity": 0.92,
            "extracted_facts": [
                {"claim": "Claim amount is $50,000", "confidence": 0.95},
                {"claim": "Policy number POL-100", "confidence": 0.90},
            ],
        }
    ]

    result = _build_rag_context_block(similar_docs)

    assert "CONTEXT FROM SIMILAR PAST CLAIMS" in result
    assert "claim_form" in result
    assert "Claim amount is $50,000" in result
    assert "Policy number POL-100" in result
    assert "END CONTEXT" in result


# ─── 8. extract_node: injects RAG context when similar docs found ─────────────

def test_extract_node_injects_rag_context_into_prompt(sample_doc, db):
    """
    When retrieve_similar_facts returns data, the LLM prompt should contain
    the 'CONTEXT FROM SIMILAR PAST CLAIMS' header.
    """
    doc, run_id = sample_doc

    similar_docs = [{
        "doc_id": "old-doc", "doc_type": "claim_form",
        "filename": "old.txt", "similarity": 0.88,
        "extracted_facts": [{"claim": "Amount $40,000", "confidence": 0.9}],
    }]

    captured_prompts = []

    def fake_llm(prompt):
        captured_prompts.append(prompt)
        return '[{"claim": "Claim amount $45,000", "confidence": 0.95, "source_doc_id": "x", "source_excerpt": "Claim amount: $45,000", "source_page": null, "is_verified": true}]', 100, 50

    initial_state = {
        "run_id": run_id,
        "classified_docs": {doc.id: "claim_form"},
        "extracted_facts": [],
        "retry_count": 0,
        "current_node": "extract",
        "last_decision": "continue",
        "hitl_pending": False,
        "conflicts": [],
        "findings": [],
        "report_html": None,
    }

    with patch("agents.nodes.extract.retrieve_similar_facts", return_value=similar_docs), \
         patch("agents.nodes.extract.embed_and_store"), \
         patch("agents.nodes.extract.call_llm", side_effect=fake_llm):
        from agents.nodes.extract import extract_node
        extract_node(initial_state, db)

    assert len(captured_prompts) == 1
    assert "CONTEXT FROM SIMILAR PAST CLAIMS" in captured_prompts[0]
    assert "Amount $40,000" in captured_prompts[0]


# ─── 9. extract_node: calls embed_and_store after successful extraction ────────

def test_extract_node_calls_embed_and_store(sample_doc, db):
    doc, run_id = sample_doc

    initial_state = {
        "run_id": run_id,
        "classified_docs": {doc.id: "claim_form"},
        "extracted_facts": [],
        "retry_count": 0,
        "current_node": "extract",
        "last_decision": "continue",
        "hitl_pending": False,
        "conflicts": [],
        "findings": [],
        "report_html": None,
    }

    with patch("agents.nodes.extract.retrieve_similar_facts", return_value=[]), \
         patch("agents.nodes.extract.call_llm", return_value=("[]", 10, 5)) as _, \
         patch("agents.nodes.extract.embed_and_store") as mock_embed:
        from agents.nodes.extract import extract_node
        extract_node(initial_state, db)

    mock_embed.assert_called_once_with(doc, db)

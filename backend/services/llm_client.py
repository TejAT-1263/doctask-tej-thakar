"""
LLM client wrapper.
In tests, this is monkey-patched to return fixture responses (no live API key needed).
In production, uses Groq (openai/gpt-oss-120b) via the OpenAI-compatible API.
Free tier: console.groq.com — set GROQ_API_KEY in .env.
Optional rotation is supported via GROQ_API_KEYS or GROQ_API_KEY_2/3/4...
"""
import os
from typing import Tuple

from config import get_settings

# Groq LLM settings
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
GROQ_MODEL    = "openai/gpt-oss-120b"  # 500 tok/s, 131k context, free developer tier


def _dedupe_keep_order(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _collect_groq_api_keys() -> list[str]:
    """
    Collect Groq keys in priority order.

    Supported env/config patterns:
    - GROQ_API_KEY
    - GROQ_API_KEYS=key1,key2,key3
    - GROQ_API_KEY_2, GROQ_API_KEY_3, ...
    """
    settings = get_settings()
    candidates: list[str] = []

    primary = settings.groq_api_key or os.environ.get("GROQ_API_KEY", "")
    if primary:
        candidates.append(primary.strip())

    csv_keys = settings.groq_api_keys or os.environ.get("GROQ_API_KEYS", "")
    if csv_keys:
        candidates.extend(k.strip() for k in csv_keys.split(","))

    for idx in range(2, 10):
        key = os.environ.get(f"GROQ_API_KEY_{idx}", "").strip()
        if key:
            candidates.append(key)

    return _dedupe_keep_order([k for k in candidates if k])


def _is_retryable_groq_error(exc: Exception) -> bool:
    """
    Decide whether another key should be tried.

    We rotate on quota / rate / auth / transient upstream failures.
    """
    status_code = getattr(exc, "status_code", None)
    if status_code in {401, 403, 408, 409, 429, 500, 502, 503, 504}:
        return True

    text = str(exc).lower()
    retryable_markers = [
        "rate_limit",
        "rate limit",
        "quota",
        "tokens per day",
        "temporarily unavailable",
        "timeout",
        "timed out",
        "connection",
        "server error",
        "service unavailable",
        "authentication",
        "invalid api key",
        "unauthorized",
        "forbidden",
    ]
    return any(marker in text for marker in retryable_markers)


def _demo_llm_response(prompt: str) -> Tuple[str, int, int]:
    prompt_lower = prompt.lower()

    if "document classification specialist" in prompt_lower:
        return (
            """{
  "doc_type": "claim_form",
  "confidence": 0.95,
  "summary": "Insurance claim form for water damage",
  "key_identifiers": ["claim number", "incident date", "claim amount"]
}""",
            100,
            50,
        )

    if "fact extraction specialist" in prompt_lower:
        return (
            """[
  {
    "claim": "Claim amount is $45,000",
    "confidence": 0.98,
    "source_doc_id": "DOC_ID_PLACEHOLDER",
    "source_excerpt": "Total claimed amount: $45,000",
    "source_page": 1,
    "is_verified": true
  },
  {
    "claim": "Incident occurred on 2026-07-15",
    "confidence": 0.97,
    "source_doc_id": "DOC_ID_PLACEHOLDER",
    "source_excerpt": "Date of incident: July 15, 2026",
    "source_page": 1,
    "is_verified": true
  }
]""",
            200,
            100,
        )

    if "document reconciliation specialist" in prompt_lower:
        return (
            """[
  {
    "doc_a_id": "doc-a",
    "doc_b_id": "doc-b",
    "field": "claim_amount",
    "value_a": "$45,000",
    "value_b": "$42,000",
    "description": "Claim form states $45,000 but adjuster notes state $42,000"
  }
]""",
            150,
            80,
        )

    if "compliance reviewer for insurance claims" in prompt_lower:
        return (
            """[
  {
    "rule_text": "Claim amount must not exceed policy limit",
    "passed": true,
    "finding": null,
    "severity": "info",
    "source_doc_id": null,
    "source_excerpt": null,
    "is_verified": true
  }
]""",
            100,
            60,
        )

    if "technical writer generating a grounded analysis report" in prompt_lower:
        return (
            "<h1>Analysis Report</h1><p>Claim amount: <cite>$45,000</cite></p>",
            300,
            200,
        )

    return ("{}", 50, 20)


def call_llm(prompt: str, max_tokens: int = 4096) -> Tuple[str, int, int]:
    """
    Call the LLM with a prompt.
    Returns: (response_text, tokens_in, tokens_out)

    Uses Groq (llama-3.3-70b-versatile) via the OpenAI-compatible API.
    Raises on API error so caller can decide to retry/skip/escalate.
    """
    api_keys = _collect_groq_api_keys()
    settings = get_settings()
    demo_mode = bool(settings.demo_mode) or os.environ.get("DEMO_MODE", "").lower() in {"1", "true", "yes"}

    if not api_keys:
        if demo_mode:
            return _demo_llm_response(prompt)
        raise RuntimeError(
            "No Groq API key configured. "
            "Set GROQ_API_KEY and optionally GROQ_API_KEYS or GROQ_API_KEY_2, "
            "then add them to .env. "
            "or set DEMO_MODE=true for a local deterministic demo."
        )

    try:
        from openai import OpenAI
    except ImportError:
        raise RuntimeError("openai package not installed. Run: pip install openai")

    errors = []
    for idx, api_key in enumerate(api_keys, start=1):
        try:
            client = OpenAI(base_url=GROQ_BASE_URL, api_key=api_key)
            response = client.chat.completions.create(
                model=GROQ_MODEL,
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            content = response.choices[0].message.content
            tok_in  = response.usage.prompt_tokens
            tok_out = response.usage.completion_tokens
            return content, tok_in, tok_out
        except Exception as exc:
            errors.append(f"key#{idx}: {exc}")
            if not _is_retryable_groq_error(exc) or idx == len(api_keys):
                break

    raise RuntimeError(
        "Groq request failed across all configured keys. "
        + " | ".join(errors)
    )


def call_llm_with_superdocs(
    document_html: str,
    instruction: str,
    session_id: str,
    approval_mode: str = "approve_all",
) -> dict:
    """
    Use SuperDocs API for document-centric LLM calls (upload → chat → approve → export).
    Returns the job result dict.
    """
    import time
    import requests
    from config import get_settings

    settings = get_settings()
    base = settings.superdocs_base_url
    headers = {
        "Authorization": f"Bearer {settings.superdocs_api_key}",
        "Content-Type": "application/json",
    }

    # Start async job
    resp = requests.post(f"{base}/v1/chat/async", headers=headers, json={
        "message": instruction,
        "session_id": session_id,
        "document_html": document_html,
        "approval_mode": approval_mode,
    })
    resp.raise_for_status()
    job_id = resp.json()["job_id"]

    # Poll until complete or awaiting_approval
    for _ in range(120):  # up to 4 minutes
        job_resp = requests.get(f"{base}/v1/jobs/{job_id}", headers=headers)
        job_resp.raise_for_status()
        job = job_resp.json()

        if job["status"] == "completed":
            return job

        if job["status"] == "failed":
            raise RuntimeError(f"SuperDocs job failed: {job.get('error', 'unknown')}")

        if job["status"] == "awaiting_approval":
            # If approval_mode is ask_every_time, approve all pending changes
            changes = job.get("metadata", {}).get("pending_changes", [])
            if changes:
                approve_resp = requests.post(
                    f"{base}/v1/chat/{session_id}/approve",
                    headers=headers,
                    json={
                        "job_id": job_id,
                        "approved": True,
                        "changes": [{"change_id": c["change_id"], "approved": True}
                                    for c in changes],
                    }
                )
                approve_resp.raise_for_status()

        time.sleep(2)

    raise TimeoutError(f"SuperDocs job {job_id} did not complete within timeout")

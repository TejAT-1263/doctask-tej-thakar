# SuperDocs API — Bugs & Gotchas Found During Integration

This file documents any issues discovered while working with the SuperDocs API, as requested in the task spec.

---

## B-001: `proposed_change_content` requires double JSON parse

**Endpoint:** `GET /v1/chat/status/{session_id}`  
**Symptom:** Accessing `response["proposed_change_content"]` returns a raw JSON string, not a dict/list.  
**Root cause:** The field is serialised as a JSON string inside the JSON response body, so a single `json.loads(response_body)` leaves it as a string.  
**Workaround:**
```python
raw = json.loads(response_body)
content = json.loads(raw["proposed_change_content"])  # second parse required
```
**Severity:** Medium — silent data corruption if you forget the second parse; the value will be a string instead of the expected structure.  
**Recommendation:** The API should return `proposed_change_content` as a first-class JSON value, not a string.

---

## B-002: `approved` field required at top level on every approve request

**Endpoint:** `POST /v1/chat/approve/{session_id}`  
**Symptom:** Omitting the top-level `approved: true` field returns a 422 or silently fails, even when the request body otherwise looks correct.  
**Workaround:** Always include `"approved": true` at the top level of the request body:
```python
{"approved": True, "item_id": "..."}
```
**Severity:** Low — easy to miss from the docs, fails loudly once you know to look.

---

## B-003: Poll loop needs explicit timeout guard

**Endpoint:** `GET /v1/chat/status/{session_id}`  
**Symptom:** If a HITL approval is never submitted (user closes browser), the poll loop in `call_llm_with_superdocs()` will spin indefinitely.  
**Workaround:** Implemented a 120-iteration cap (120 × 5s = 10 min) with a `RuntimeError("HITL timeout")` after the cap.  
**Recommendation:** SuperDocs should expose a `timeout_seconds` parameter on the async chat endpoint, or provide a webhook/callback option.

---

## B-004: Session context not preserved across approve/reject cycles

**Endpoint:** `POST /v1/chat/approve/{session_id}` → `GET /v1/chat/status/{session_id}`  
**Symptom:** After a reviewer rejects a proposed change and the agent regenerates, the second `waiting_for_approval` response does not include any indication that this is a retry (no `attempt_number`, no `previous_rejection_reason`). The reviewer has no way to know they already saw and rejected an earlier version.  
**Workaround:** Implemented a `retry_count` field in local state and surface it in the review UI ("Attempt 2 of 3"). But this is tracked client-side only — the SuperDocs session itself doesn't expose it.  
**Recommendation:** Add an `attempt_number` field to the `waiting_for_approval` status payload, and optionally surface the previous reviewer's rejection comment so the second attempt can show what changed.

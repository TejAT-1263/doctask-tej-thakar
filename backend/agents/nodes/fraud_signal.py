"""
FraudSignalNode — Stage 1, between extract and reconcile.

Deterministic, rule-based signal detection.  No LLM is used here — every signal
is the direct output of a pattern match against extracted facts.

Design principles:
  - CONSERVATIVE: only flag when the evidence is unambiguous or explicitly mentioned
  - Signals are labelled "warrants review", not "is fraudulent"
  - Each signal carries a confidence level (LOW / MEDIUM / HIGH)
  - India-specific: IRDAI regulations, INR amounts, Indian date conventions
  - A single signal is never sufficient to conclude fraud; signals are informational

India context:
  - IRDAI = Insurance Regulatory and Development Authority of India
  - Standard health insurance waiting period: 30 days (accidents exempt)
  - Pre-Existing Disease (PED) waiting: typically 2–4 years
  - Claim intimation deadline: many policies require intimation within 30 days of loss
  - Amounts in INR (₹); Indian numbering uses lakhs (1,00,000) and crores (1,00,00,000)
"""
import re
import time
from datetime import datetime, date
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from agents.state import GraphState, NodeDecision, FraudSignal, ExtractedFact
from agents.nodes.base import log_node


# ─── Date parsing ─────────────────────────────────────────────────────────────

_MONTH_MAP = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4,
    "jun": 6, "jul": 7, "aug": 8, "sep": 9, "sept": 9,
    "oct": 10, "nov": 11, "dec": 12,
}


def _parse_indian_date(text: str) -> Optional[date]:
    """
    Parse a date from Indian insurance document text.
    Handles: DD/MM/YYYY, DD-MM-YYYY, YYYY-MM-DD, D Month YYYY
    Returns None if unparseable — never raises.
    """
    text = text.strip()

    # ISO format YYYY-MM-DD
    m = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})", text)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass

    # DD/MM/YYYY or DD-MM-YYYY (Indian standard)
    m = re.match(r"(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})", text)
    if m:
        try:
            # Assume DD/MM/YYYY (Indian convention)
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            pass

    # D Month YYYY  (e.g., "15 August 2024" or "1st January 2024")
    m = re.match(
        r"(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)\s+(\d{4})",
        text, re.IGNORECASE
    )
    if m:
        day = int(m.group(1))
        month = _MONTH_MAP.get(m.group(2).lower())
        year = int(m.group(3))
        if month:
            try:
                return date(year, month, day)
            except ValueError:
                pass

    return None


def _extract_dates_from_facts(
    facts: List[ExtractedFact],
    keywords: List[str],
) -> List[Tuple[date, str, str]]:
    """
    Search extracted facts for dates associated with given keywords.
    Returns list of (parsed_date, raw_text_snippet, source_doc_id).
    """
    results = []
    date_pattern = re.compile(
        r"""
        \d{4}-\d{1,2}-\d{1,2}           |  # ISO
        \d{1,2}[/\-]\d{1,2}[/\-]\d{4}  |  # DD/MM/YYYY
        \d{1,2}(?:st|nd|rd|th)?\s+
          (?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|
             May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|
             Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{4}
        """,
        re.VERBOSE | re.IGNORECASE,
    )

    for fact in facts:
        claim_lower = fact["claim"].lower()
        if not any(kw in claim_lower for kw in keywords):
            continue
        # Search both the claim text and source_excerpt
        for haystack in (fact["claim"], fact.get("source_excerpt", "")):
            for m in date_pattern.finditer(haystack):
                d = _parse_indian_date(m.group(0))
                if d:
                    results.append((d, m.group(0), fact["source_doc_id"]))

    return results


# ─── INR amount parsing ───────────────────────────────────────────────────────

def _parse_inr_amount(text: str) -> Optional[float]:
    """
    Parse INR amounts from text.  Handles:
      ₹50,000  /  Rs. 1,00,000  /  INR 5 lakh  /  50000
    Returns float amount in rupees, or None.
    """
    text = text.replace(",", "").replace("₹", "").replace("Rs.", "").replace("Rs", "")
    text = text.strip()

    # Handle lakh / crore notation
    m = re.search(r"([\d.]+)\s*(?:lakh|lac)", text, re.IGNORECASE)
    if m:
        try:
            return float(m.group(1)) * 100_000
        except ValueError:
            pass

    m = re.search(r"([\d.]+)\s*crore", text, re.IGNORECASE)
    if m:
        try:
            return float(m.group(1)) * 10_000_000
        except ValueError:
            pass

    # Plain number
    m = re.search(r"[\d]+(?:\.\d+)?", text)
    if m:
        try:
            return float(m.group(0))
        except ValueError:
            pass

    return None


# ─── Signal detectors ─────────────────────────────────────────────────────────

def _check_temporal_paradox(facts: List[ExtractedFact]) -> List[FraudSignal]:
    """
    HIGH CONFIDENCE: Detect if treatment/hospitalisation begins before the incident date,
    or if the claim is filed before the incident occurred.
    """
    signals = []

    incident_dates = _extract_dates_from_facts(
        facts, [
            "incident", "accident", "loss", "event", "occurrence",
            "stolen", "theft", "fire", "flood", "damage", "collision",
            "injured", "injury", "fell", "met with", "occurred", "happened",
            "date of loss", "date of incident", "date of accident",
        ]
    )
    treatment_dates = _extract_dates_from_facts(
        facts, [
            "treatment", "hospitalisation", "hospitalization",
            "admission", "admitted", "surgery", "procedure", "diagnosis",
            "hospital", "medical", "discharge", "operation", "consultation",
            "ward", "icu", "emergency",
        ]
    )
    claim_dates = _extract_dates_from_facts(
        facts, [
            "claim filed", "claim submitted", "claim date", "date of claim",
            "intimation", "notif", "claim registered", "claim lodged",
            "reported", "registration", "date of filing", "filing date",
            "claim no", "claim number", "docket",
        ]
    )

    if not incident_dates:
        return signals

    earliest_incident = min(d for d, _, _ in incident_dates)

    # Treatment before incident?
    for t_date, t_raw, t_doc in treatment_dates:
        if t_date < earliest_incident:
            earliest_incident_raw = next(raw for d, raw, _ in incident_dates if d == earliest_incident)
            signals.append(FraudSignal(
                signal_id="TEMPORAL_PARADOX_TREATMENT",
                title="Treatment/Admission precedes incident date",
                description=(
                    f"The document records treatment or hospitalisation on {t_raw}, "
                    f"which is before the stated incident date of {earliest_incident_raw}. "
                    "This warrants verification — possible date error or pre-existing condition."
                ),
                confidence="HIGH",
                evidence=f"Treatment: {t_raw} | Incident: {earliest_incident_raw}",
                source_doc_ids=list({t_doc} | {d for _, _, d in incident_dates}),
                regulatory_ref=None,
            ))
            break  # One signal per category is enough; avoid noise

    # Claim filed before incident?
    for c_date, c_raw, c_doc in claim_dates:
        if c_date < earliest_incident:
            earliest_incident_raw = next(raw for d, raw, _ in incident_dates if d == earliest_incident)
            signals.append(FraudSignal(
                signal_id="TEMPORAL_PARADOX_CLAIM",
                title="Claim filed before incident date",
                description=(
                    f"The claim appears to have been filed on {c_raw}, "
                    f"before the stated incident date of {earliest_incident_raw}. "
                    "This is a strong indicator of a date error or data entry mistake and must be clarified."
                ),
                confidence="HIGH",
                evidence=f"Claim date: {c_raw} | Incident date: {earliest_incident_raw}",
                source_doc_ids=list({c_doc} | {d for _, _, d in incident_dates}),
                regulatory_ref=None,
            ))
            break

    return signals


def _check_short_policy_tenure(facts: List[ExtractedFact]) -> List[FraudSignal]:
    """
    MEDIUM CONFIDENCE: Incident within 30 days of policy inception.
    Under IRDAI Health Insurance Regulations, there is typically a 30-day waiting period
    for non-accident claims. Accident claims are usually exempt.
    """
    signals = []

    inception_dates = _extract_dates_from_facts(
        facts, [
            "policy inception", "policy start", "commencement", "effective date",
            "policy effective", "policy date", "inception date",
            "policy issued", "policy commenced", "cover start", "valid from",
            "start date", "issue date", "policy period from",
        ]
    )
    incident_dates = _extract_dates_from_facts(
        facts, [
            "incident", "accident", "loss", "event", "date of loss",
            "occurrence", "date of incident", "stolen", "theft", "fire",
            "flood", "damage", "collision", "injured", "injury",
            "happened", "occurred",
        ]
    )

    if not inception_dates or not incident_dates:
        return signals

    earliest_inception = min(d for d, _, _ in inception_dates)
    earliest_incident = min(d for d, _, _ in incident_dates)

    delta_days = (earliest_incident - earliest_inception).days

    if 0 <= delta_days <= 30:
        inception_raw = next(raw for d, raw, _ in inception_dates if d == earliest_inception)
        incident_raw = next(raw for d, raw, _ in incident_dates if d == earliest_incident)
        signals.append(FraudSignal(
            signal_id="SHORT_POLICY_TENURE",
            title="Incident within 30 days of policy inception",
            description=(
                f"The policy incepted on {inception_raw} and the loss occurred on "
                f"{incident_raw} — a gap of {delta_days} day(s). "
                "IRDAI regulations typically impose a 30-day waiting period for non-accident "
                "claims. Confirm whether this is an accident claim (waiting period exempt) "
                "and verify the inception date against the policy document."
            ),
            confidence="MEDIUM",
            evidence=f"Inception: {inception_raw} | Incident: {incident_raw} | Gap: {delta_days} days",
            source_doc_ids=list(
                {d for _, _, d in inception_dates} | {d for _, _, d in incident_dates}
            ),
            regulatory_ref="IRDAI Health Insurance Regulations, 2016 — Reg. 8 (Waiting Period)",
        ))
    elif delta_days < 0:
        # Incident before policy inception — this is a definite coverage issue, not a fraud signal
        # (it is a rule-check concern, not a fraud signal — leave it for rule_check)
        pass

    return signals


def _check_round_claim_amount(facts: List[ExtractedFact]) -> List[FraudSignal]:
    """
    LOW CONFIDENCE: Claim amount is a suspiciously round number in INR.
    Round amounts like ₹1,00,000 / ₹5,00,000 are common in India but statistically
    over-represented in fraudulent claims. Flagged as LOW confidence — this is the
    weakest signal and should only be used in conjunction with other signals.
    """
    signals = []
    ROUND_THRESHOLD = 50_000  # multiple of ₹50,000

    # Look for claim amount facts
    amount_facts = [
        f for f in facts
        if any(kw in f["claim"].lower() for kw in
               ["claim amount", "claimed amount", "sum claimed", "amount claimed",
                "hospital bill", "medical expenses", "repair cost", "damage amount",
                "total amount", "bill amount", "invoice amount", "sum insured",
                "sum assured", "cover amount", "compensation", "reimbursement",
                "estimated loss", "assessed value", "idv", "insured declared value"])
    ]

    for fact in amount_facts:
        # Try to parse amount from claim text + excerpt
        for haystack in (fact["claim"], fact.get("source_excerpt", "")):
            amount = _parse_inr_amount(haystack)
            if amount and amount > 0 and round(amount) % ROUND_THRESHOLD == 0:
                signals.append(FraudSignal(
                    signal_id="ROUND_CLAIM_AMOUNT",
                    title="Claim amount is a round figure",
                    description=(
                        f"The claimed amount (₹{amount:,.0f}) is an exact multiple of "
                        f"₹{ROUND_THRESHOLD:,}. Round amounts are common in Indian claims "
                        "but are statistically more frequent in inflated claims. "
                        "This is a weak signal — verify with original invoices/bills."
                    ),
                    confidence="LOW",
                    evidence=f"Amount: ₹{amount:,.0f} from fact: \"{fact['claim'][:100]}\"",
                    source_doc_ids=[fact["source_doc_id"]],
                    regulatory_ref=None,
                ))
                break  # One signal per fact is enough
        else:
            continue
        break  # Report at most one round-amount signal per run

    return signals


def _check_late_intimation(facts: List[ExtractedFact]) -> List[FraudSignal]:
    """
    MEDIUM CONFIDENCE: Claim filed more than 30 days after the incident.
    Most Indian insurance policies (health, motor, property) require intimation
    within 30 days of the loss date per IRDAI guidelines.
    """
    signals = []

    incident_dates = _extract_dates_from_facts(
        facts, [
            "incident", "accident", "loss", "occurrence", "date of loss",
            "stolen", "theft", "fire", "flood", "damage", "collision",
            "injured", "injury", "happened", "occurred",
        ]
    )
    claim_dates = _extract_dates_from_facts(
        facts, [
            "claim filed", "claim submitted", "claim date", "intimation date",
            "date of intimation", "registration date", "claim registered",
            "claim lodged", "reported to", "date of filing", "filing date",
            "intimated", "informed", "notified",
        ]
    )

    if not incident_dates or not claim_dates:
        return signals

    earliest_incident = min(d for d, _, _ in incident_dates)
    latest_claim = max(d for d, _, _ in claim_dates)

    delta_days = (latest_claim - earliest_incident).days

    if delta_days > 30:
        incident_raw = next(raw for d, raw, _ in incident_dates if d == earliest_incident)
        claim_raw = next(raw for d, raw, _ in claim_dates if d == latest_claim)
        signals.append(FraudSignal(
            signal_id="LATE_CLAIM_INTIMATION",
            title=f"Claim filed {delta_days} days after incident",
            description=(
                f"The incident occurred on {incident_raw} but the claim was filed on "
                f"{claim_raw} — a delay of {delta_days} days "
                f"({delta_days // 30} month(s)). "
                "Most Indian insurance policies require claim intimation within 30 days "
                "of the incident per IRDAI guidelines. Verify whether the insurer was "
                "notified earlier and obtain the policyholder's explanation for the delay."
            ),
            confidence="MEDIUM",
            evidence=f"Incident: {incident_raw} | Claim filed: {claim_raw} | Delay: {delta_days} days",
            source_doc_ids=list(
                {d for _, _, d in incident_dates} | {d for _, _, d in claim_dates}
            ),
            regulatory_ref="IRDAI Guidelines on Claim Settlement — intimation timelines",
        ))

    return signals


def _check_contact_detail_inconsistency(facts: List[ExtractedFact]) -> List[FraudSignal]:
    """
    MEDIUM CONFIDENCE: Different phone numbers for the claimant mentioned across documents.
    A legitimate claimant should have consistent contact details. Multiple different phone
    numbers may indicate document fabrication or identity inconsistency.
    """
    signals = []

    phone_pattern = re.compile(
        r"""
        (?:
            \+91[\s\-]?          |   # +91 prefix
            0?                       # optional leading 0
        )
        [6-9]\d{9}               |   # 10-digit mobile
        \d{2,4}[\s\-]\d{6,8}        # landline with STD code
        """,
        re.VERBOSE,
    )

    # Collect phone numbers per document
    doc_phones: dict[str, set[str]] = {}
    for fact in facts:
        doc_id = fact["source_doc_id"]
        for haystack in (fact["claim"], fact.get("source_excerpt", "")):
            for m in phone_pattern.finditer(haystack):
                # Normalise: keep only digits
                digits = re.sub(r"\D", "", m.group(0))
                if len(digits) >= 10:
                    # Use last 10 digits for comparison (strip +91 / 0 prefix)
                    normalised = digits[-10:]
                    doc_phones.setdefault(doc_id, set()).add(normalised)

    # Find numbers that appear in one doc but NOT in others
    all_numbers: set[str] = set()
    for nums in doc_phones.values():
        all_numbers |= nums

    if len(all_numbers) < 2:
        return signals  # Only one unique number or none — no inconsistency

    # Check: are the same numbers present across all documents that mention phones?
    docs_with_phones = {doc_id: nums for doc_id, nums in doc_phones.items() if nums}
    if len(docs_with_phones) < 2:
        return signals  # Need at least two docs to compare

    # Find numbers that are exclusive to a single document
    exclusive: dict[str, list[str]] = {}
    for doc_id, nums in docs_with_phones.items():
        other_nums = set()
        for other_id, other_set in docs_with_phones.items():
            if other_id != doc_id:
                other_nums |= other_set
        excl = nums - other_nums
        if excl:
            exclusive[doc_id] = sorted(excl)

    if len(exclusive) >= 2:
        evidence_parts = []
        all_doc_ids = []
        for doc_id, nums in exclusive.items():
            all_doc_ids.append(doc_id)
            evidence_parts.append(f"{doc_id[:8]}…: {', '.join(nums)}")

        signals.append(FraudSignal(
            signal_id="CONTACT_DETAIL_INCONSISTENCY",
            title="Different contact numbers across documents",
            description=(
                "Different phone numbers for the claimant were found in different documents. "
                "A genuine claim should have consistent contact details. "
                "This may indicate a data entry error, or that the documents originate from "
                "different sources. Verify the correct contact number directly with the policyholder."
            ),
            confidence="MEDIUM",
            evidence=" | ".join(evidence_parts),
            source_doc_ids=all_doc_ids,
            regulatory_ref=None,
        ))

    return signals


def _check_declaration_inconsistency(facts: List[ExtractedFact]) -> List[FraudSignal]:
    """
    HIGH CONFIDENCE: Detect contradictions between the policyholder's lifestyle /
    health declaration and actual medical evidence in the claim documents.

    This is one of the most common fraud patterns in Indian health insurance:
    a claimant declares "no pre-existing conditions" at inception, then files a
    claim that reveals the undisclosed condition.

    Works on a SINGLE document — declaration and medical evidence often appear in
    different sections of the same claim form / discharge summary.

    India context: IRDAI requires material disclosure at policy inception. Failure
    to disclose a pre-existing condition is grounds for claim repudiation under
    Section 45 of the Insurance Act, 1938.
    """
    signals = []

    # Map of condition → (declaration negatives, medical positives)
    CONDITIONS: dict[str, tuple[list[str], list[str]]] = {
        "hypertension": (
            ["no hypertension", "not hypertensive", "no bp issue", "no high blood pressure",
             "no history of hypertension", "no htn", "bp normal", "normal blood pressure",
             "no blood pressure", "normotensive"],
            ["hypertension", "hypertensive", "high blood pressure", "hbp", "antihypertensive",
             "amlodipine", "atenolol", "losartan", "telmisartan", "uncontrolled bp",
             "uncontrolled hypertension", "elevated bp", "bp:", "bp :", "bp elevated"],
        ),
        "cardiac": (
            ["no cardiac", "no heart disease", "no cardiac history", "no chest pain history",
             "no heart attack", "no angina", "no coronary", "no ihd", "no cad",
             "no cardiac history", "no heart condition"],
            ["cardiac", "heart attack", "myocardial infarction", "mi", "angina",
             "coronary artery", "cad", "ihd", "ischaemic heart", "ischemic heart",
             "ecg changes", "troponin", "stent", "angioplasty", "bypass", "cardiac arrest"],
        ),
        "diabetes": (
            ["no diabetes", "non-diabetic", "not diabetic", "no sugar", "no history of diabetes",
             "no dm", "blood sugar normal", "no diabetic history"],
            ["diabetes", "diabetic", "blood sugar", "hba1c", "fasting glucose", "insulin",
             "metformin", "glipizide", "dm type", "type 2 dm", "type 1 dm",
             "uncontrolled diabetes", "hyperglycaemia", "hyperglycemia"],
        ),
        "smoker": (
            ["non-smoker", "not a smoker", "no smoking history", "does not smoke",
             "never smoked", "non smoker", "no tobacco", "no cigarette", "no smoking"],
            ["smoker", "smoking", "tobacco use", "tobacco", "cigarette", "bidi",
             "chewing tobacco", "smoker since", "pack years", "nicotine", "betel nut",
             "gutkha"],
        ),
        "alcohol": (
            ["non-alcoholic", "no alcohol", "does not drink", "teetotaler",
             "no history of alcohol", "no alcoholism", "no drinking"],
            ["alcoholic", "alcohol use", "drinks alcohol", "etoh", "ethanol",
             "liver disease", "cirrhosis", "alcohol dependence"],
        ),
    }

    for condition, (neg_kws, pos_kws) in CONDITIONS.items():
        # Find facts containing a declaration that DENIES the condition
        decl_facts = [
            f for f in facts
            if any(
                kw in f["claim"].lower() or kw in (f.get("source_excerpt") or "").lower()
                for kw in neg_kws
            )
        ]
        # Find facts containing medical evidence that AFFIRMS the condition
        medical_facts = [
            f for f in facts
            if any(
                kw in f["claim"].lower() or kw in (f.get("source_excerpt") or "").lower()
                for kw in pos_kws
            )
        ]

        if not decl_facts or not medical_facts:
            continue  # No contradiction — skip

        # Avoid false positives: check the declaration fact isn't just reporting
        # someone else's condition (e.g. "family history of diabetes")
        decl_fact = decl_facts[0]
        if any(fp in decl_fact["claim"].lower() for fp in ["family history", "father", "mother", "sibling"]):
            continue

        decl_excerpt  = decl_fact["claim"][:150]
        evid_excerpt  = medical_facts[0]["claim"][:150]
        all_doc_ids   = list({
            f["source_doc_id"] for f in decl_facts + medical_facts
            if f.get("source_doc_id")
        })

        signals.append(FraudSignal(
            signal_id=f"DECLARATION_INCONSISTENCY_{condition.upper()}",
            title=f"Lifestyle declaration conflicts with medical evidence — {condition}",
            description=(
                f"The claim documents contain a declaration denying {condition} "
                f"but also include medical evidence of {condition}. "
                "In Indian health insurance, failure to disclose a pre-existing condition "
                "at policy inception is a material non-disclosure. "
                "The adjuster must obtain the complete medical history and verify whether "
                "this condition pre-dated the policy inception date."
            ),
            confidence="HIGH",
            evidence=(
                f"Declaration: \"{decl_excerpt}\" | "
                f"Medical evidence: \"{evid_excerpt}\""
            ),
            source_doc_ids=all_doc_ids,
            regulatory_ref=(
                "Insurance Act 1938, Section 45 — material non-disclosure; "
                "IRDAI Health Insurance Regulations 2016, Reg. 6 (pre-existing diseases)"
            ),
        ))

    return signals


# ─── Node entry point ─────────────────────────────────────────────────────────

def fraud_signal_node(state: GraphState, db: Session) -> GraphState:
    """
    Run all fraud signal detectors against extracted facts.
    Returns updated state with fraud_signals populated.

    This node NEVER modifies the pipeline outcome — it only adds signals to state.
    The disposition recommendation and human adjuster take signals into account.
    """
    run_id = state["run_id"]
    facts = state.get("extracted_facts", [])

    if not facts:
        log_node(db, run_id, "fraud_signal", stage=1,
                 decision=NodeDecision.SKIP,
                 output_summary="No facts available — skipping signal detection")
        return {
            **state,
            "fraud_signals": [],
            "current_node": "fraud_signal",
            "last_decision": NodeDecision.SKIP,
        }

    t0 = time.monotonic()
    all_signals: List[FraudSignal] = []

    # Run each detector independently — a failure in one does not stop others
    detectors = [
        ("temporal_paradox",              _check_temporal_paradox),
        ("short_policy_tenure",           _check_short_policy_tenure),
        ("round_claim_amount",            _check_round_claim_amount),
        ("late_claim_intimation",         _check_late_intimation),
        ("contact_detail_inconsistency",  _check_contact_detail_inconsistency),
        ("declaration_inconsistency",     _check_declaration_inconsistency),
    ]

    detector_results = {}
    for name, fn in detectors:
        try:
            found = fn(facts)
            all_signals.extend(found)
            detector_results[name] = len(found)
        except Exception as e:
            detector_results[name] = f"error: {e}"

    duration = int((time.monotonic() - t0) * 1000)
    high   = sum(1 for s in all_signals if s["confidence"] == "HIGH")
    medium = sum(1 for s in all_signals if s["confidence"] == "MEDIUM")
    low    = sum(1 for s in all_signals if s["confidence"] == "LOW")

    log_node(
        db, run_id, "fraud_signal", stage=1,
        decision=NodeDecision.CONTINUE,
        output_summary=(
            f"{len(all_signals)} signal(s) detected "
            f"(HIGH={high}, MEDIUM={medium}, LOW={low}) | "
            + ", ".join(f"{k}={v}" for k, v in detector_results.items())
        ),
        duration_ms=duration,
    )

    return {
        **state,
        "fraud_signals": all_signals,
        "current_node": "fraud_signal",
        "last_decision": NodeDecision.CONTINUE,
    }

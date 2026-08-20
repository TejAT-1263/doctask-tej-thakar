from pathlib import Path

from reportlab.lib.colors import black, red, white
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas


OUT_DIR = Path("/Users/tejthakar/Downloads/SuperDocs/doctask-tej-thakar/output/pdf")


def line(c, x1, y, x2):
    c.setStrokeColor(black)
    c.setLineWidth(0.6)
    c.line(x1, y, x2, y)


def field(c, label, value, x, y, x2):
    c.setFont("Helvetica", 10)
    c.drawString(x, y, label)
    line(c, x + 44 * mm, y - 2, x2)
    c.drawString(x + 45 * mm, y, value)


def section_bar(c, text, y):
    c.setFillColor(red)
    c.rect(18 * mm, y - 4, 174 * mm, 11, stroke=0, fill=1)
    c.setFillColor(white)
    c.setFont("Helvetica-Bold", 11)
    c.drawCentredString(105 * mm, y, text)
    c.setFillColor(black)


def draw_wrapped_lines(c, lines, x, y, step=6.3):
    c.setFont("Helvetica", 10)
    for text in lines:
        c.drawString(x, y, text)
        y -= step * mm
    return y


def render_variant(filename: str, title_note: str, values: dict):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    target = OUT_DIR / filename
    c = canvas.Canvas(str(target), pagesize=A4)
    width, height = A4

    y = height - 28 * mm
    c.setFont("Helvetica", 16)
    c.drawString(18 * mm, y, "HDFC ERGO General Insurance Company Limited")

    y -= 12 * mm
    c.setFillColor(red)
    c.setFont("Helvetica-Bold", 15)
    c.drawString(18 * mm, y, "CLAIM FORM FOR HEALTH INSURANCE POLICIES OTHER THAN")
    y -= 7 * mm
    c.drawString(18 * mm, y, "TRAVEL AND PERSONAL ACCIDENT")
    c.setFillColor(black)

    y -= 11 * mm
    c.setFont("Helvetica-Bold", 15)
    c.drawString(18 * mm, y, "CLAIM FORM - PART A")
    c.setFont("Helvetica", 10)
    c.drawRightString(width - 18 * mm, y, "(To be filled in block letters)")

    y -= 10 * mm
    c.drawString(18 * mm, y, "To be filled in by the Insured. The issue of this form is not to be taken as an admission of liability")

    y -= 12 * mm
    section_bar(c, "SECTION A - DETAILS OF PRIMARY INSURED", y)
    y -= 10 * mm
    field(c, "Policy No.:", values["policy_no"], 18 * mm, y, 96 * mm)
    field(c, "Certificate No.:", "NA", 110 * mm, y, 190 * mm)
    y -= 8 * mm
    field(c, "Name:", values["name"], 18 * mm, y, 190 * mm)
    y -= 8 * mm
    field(c, "Address:", values["address"], 18 * mm, y, 190 * mm)
    y -= 8 * mm
    field(c, "City:", values["city"], 18 * mm, y, 96 * mm)
    field(c, "State:", values["state"], 110 * mm, y, 150 * mm)
    field(c, "Pincode:", values["pincode"], 150 * mm, y, 190 * mm)
    y -= 8 * mm
    field(c, "Phone No.:", values["phone"], 18 * mm, y, 96 * mm)
    field(c, "Email ID:", values["email"], 110 * mm, y, 190 * mm)

    y -= 12 * mm
    section_bar(c, "SECTION B - DETAILS OF INSURANCE HISTORY", y)
    y -= 10 * mm
    y = draw_wrapped_lines(c, values["history_lines"], 18 * mm, y)

    y -= 3 * mm
    section_bar(c, "SECTION C - DETAILS OF INSURED PERSON HOSPITALISED", y)
    y -= 10 * mm
    field(c, "Patient Name:", values["patient_name"], 18 * mm, y, 110 * mm)
    field(c, "Age:", values["age"], 125 * mm, y, 190 * mm)
    y -= 8 * mm
    field(c, "Date of Birth:", values["dob"], 18 * mm, y, 110 * mm)
    field(c, "Gender:", values["gender"], 125 * mm, y, 190 * mm)
    y -= 8 * mm
    field(c, "Occupation:", values["occupation"], 18 * mm, y, 110 * mm)
    field(c, "Mobile No.:", values["mobile"], 125 * mm, y, 190 * mm)

    y -= 12 * mm
    section_bar(c, "SECTION D - DETAILS OF HOSPITALIZATION", y)
    y -= 10 * mm
    y = draw_wrapped_lines(c, values["hospital_lines"], 18 * mm, y)

    y -= 3 * mm
    section_bar(c, "SECTION E - DETAILS OF CLAIM", y)
    y -= 10 * mm
    y = draw_wrapped_lines(c, values["claim_lines"], 18 * mm, y)

    y -= 3 * mm
    section_bar(c, values["flag_title"], y)
    y -= 10 * mm
    y = draw_wrapped_lines(c, values["flag_lines"], 18 * mm, y)

    c.setFont("Helvetica", 7)
    c.drawString(
        18 * mm,
        9 * mm,
        f"Placeholder values only. Synthetic claim test document. Variant: {title_note}.",
    )

    c.save()
    print(target)


def main():
    render_variant(
        "health_claim_strong_conflict.pdf",
        "strong conflict",
        {
            "policy_no": "HLT-IND-2026-113201",
            "name": "Mr. Vivek Sharma",
            "address": "D-702, Lakeview Towers, Pune, Maharashtra, 411045",
            "city": "Pune",
            "state": "Maharashtra",
            "pincode": "411045",
            "phone": "9876543210",
            "email": "vivek.sharma@example.com",
            "history_lines": [
                "a) First insurance without break: 01-Jan-2024",
                "b) Prior hospitalization in last four years: No",
                "c) Declaration in proposal: No chronic illness, no prior renal treatment",
            ],
            "patient_name": "Mr. Vivek Sharma",
            "age": "41 Years",
            "dob": "12-Oct-1984",
            "gender": "Male",
            "occupation": "Service",
            "mobile": "9876543210",
            "hospital_lines": [
                "a) Hospital: Horizon Care Hospital, Pune",
                "b) Admission: 09-Aug-2026 07:30 PM | Discharge: 11-Aug-2026 10:15 AM",
                "c) Diagnosis declared in claim: Sudden acute abdominal infection",
                "d) Treating physician note attached: Chronic kidney disease under treatment since 2023",
                "e) Lab note attached: Diabetes and renal markers indicate longstanding disease profile",
            ],
            "claim_lines": [
                "i) Pre-hospitalization: Rs. 12,000",
                "ii) Hospitalization: Rs. 1,92,000",
                "iii) Post-hospitalization: Rs. 24,000",
                "iv) Total claimed amount: Rs. 2,28,000",
            ],
            "flag_title": "SECTION F - STRONG CONFLICTS IDENTIFIED IN THIS FORM",
            "flag_lines": [
                "1. Claim says no prior chronic illness, but physician note says CKD treatment since 2023.",
                "2. Hospital diagnosis narrative conflicts with attached doctor statement and lab history.",
                "3. Prior hospitalization marked 'No', but attached treatment note implies ongoing specialist care.",
                "4. High risk of material non-disclosure and inconsistent medical declaration.",
            ],
        },
    )

    render_variant(
        "health_claim_strong_signal.pdf",
        "strong signal",
        {
            "policy_no": "HLT-IND-2026-113202",
            "name": "Mrs. Neha Arora",
            "address": "Flat 18B, Riverfront Residency, Noida, Uttar Pradesh, 201301",
            "city": "Noida",
            "state": "Uttar Pradesh",
            "pincode": "201301",
            "phone": "9811102244",
            "email": "neha.arora@example.com",
            "history_lines": [
                "a) First insurance without break: 20-Jul-2026",
                "b) Prior hospitalization in last four years: No",
                "c) Lifestyle declaration: Non-smoker, no cardiac history, no hypertension",
            ],
            "patient_name": "Mrs. Neha Arora",
            "age": "39 Years",
            "dob": "04-Feb-1987",
            "gender": "Female",
            "occupation": "Self employed",
            "mobile": "9811102244",
            "hospital_lines": [
                "a) Hospital: Metro Heart Institute, Noida",
                "b) Admission: 08-Aug-2026 02:10 AM | Discharge: 10-Aug-2026 09:30 PM",
                "c) Diagnosis: Acute cardiac episode with uncontrolled hypertension",
                "d) Emergency note: Tobacco use and untreated hypertension noted in past records",
                "e) Policy age at claim time: Less than 3 weeks from inception",
            ],
            "claim_lines": [
                "i) Ambulance and pre-hospitalization: Rs. 18,700",
                "ii) Hospitalization: Rs. 2,48,000",
                "iii) Medicines and post-care: Rs. 31,400",
                "iv) Total claimed amount: Rs. 2,98,100",
            ],
            "flag_title": "SECTION F - STRONG RISK SIGNALS PRESENT",
            "flag_lines": [
                "1. Very short policy tenure before high-value hospitalization.",
                "2. Emergency records contradict declared lifestyle and medical history.",
                "3. Cardiac event shortly after policy inception warrants strict underwriting review.",
                "4. Material signal of non-disclosure even before external corroboration.",
            ],
        },
    )

    render_variant(
        "health_claim_self_flagging_reject.pdf",
        "self flagging reject",
        {
            "policy_no": "HLT-IND-2026-113203",
            "name": "Mr. Karan Sethi",
            "address": "A-33, Green Park Extension, New Delhi, Delhi, 110016",
            "city": "New Delhi",
            "state": "Delhi",
            "pincode": "110016",
            "phone": "9899011177",
            "email": "karan.sethi@example.com",
            "history_lines": [
                "a) First insurance without break: 01-Aug-2026",
                "b) Prior hospitalization in last four years: Yes - 2025 liver-related admission",
                "c) Proposal disclosure filed with insurer: No prior liver disease mentioned",
            ],
            "patient_name": "Mr. Karan Sethi",
            "age": "44 Years",
            "dob": "27-Jun-1982",
            "gender": "Male",
            "occupation": "Business",
            "mobile": "9899011177",
            "hospital_lines": [
                "a) Hospital: City Care Super Speciality Hospital, Delhi",
                "b) Admission: 09-Aug-2026 11:50 PM | Discharge: 12-Aug-2026 01:10 PM",
                "c) Diagnosis: Chronic liver disease flare-up with alcohol-related complications",
                "d) Consultant note: Known case under treatment before policy start date",
                "e) Claimant remarks: 'This should still be covered because I paid premium this month.'",
            ],
            "claim_lines": [
                "i) Hospitalization: Rs. 3,12,000",
                "ii) ICU and diagnostics: Rs. 88,000",
                "iii) Total claimed amount: Rs. 4,00,000",
                "iv) Special note: Claimant requests fast approval despite pre-existing history",
            ],
            "flag_title": "SECTION F - FORM ITSELF INDICATES REJECTION RISK",
            "flag_lines": [
                "1. Prior hospitalization and known chronic liver disease are admitted inside the form.",
                "2. Proposal disclosure conflicts with the medical history admitted in this same claim packet.",
                "3. Alcohol-related chronic condition and pre-policy treatment strongly indicate exclusion review.",
                "4. This file self-flags for pre-existing disease, non-disclosure, and waiting-period failure.",
            ],
        },
    )


if __name__ == "__main__":
    main()

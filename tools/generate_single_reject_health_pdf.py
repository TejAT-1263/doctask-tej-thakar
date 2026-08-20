from pathlib import Path

from reportlab.lib.colors import black, red, white
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas


OUT = Path("/Users/tejthakar/Downloads/SuperDocs/doctask-tej-thakar/output/pdf/health_claim_single_reject.pdf")


def line(c, x1, y, x2):
    c.setStrokeColor(black)
    c.setLineWidth(0.6)
    c.line(x1, y, x2, y)


def field(c, label, value, x, y, w, label_w=115):
    c.setFont("Helvetica", 10)
    c.drawString(x, y, label)
    line(c, x + label_w, y - 2, x + w)
    c.setFont("Helvetica", 10)
    c.drawString(x + label_w + 4, y, value)


def checkbox(c, label, checked, x, y):
    c.rect(x, y - 8, 10, 10, stroke=1, fill=0)
    if checked:
        c.setFont("Helvetica-Bold", 12)
        c.drawString(x + 1, y - 8, "X")
    c.setFont("Helvetica", 10)
    c.drawString(x + 14, y - 1, label)


def section_bar(c, text, y):
    c.setFillColor(red)
    c.rect(18 * mm, y - 4, 174 * mm, 11, stroke=0, fill=1)
    c.setFillColor(white)
    c.setFont("Helvetica-Bold", 11)
    c.drawCentredString(105 * mm, y, text)
    c.setFillColor(black)


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(OUT), pagesize=A4)
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
    field(c, "a) Policy No.:", "HLT-IND-2026-009441", 18 * mm, y, 82 * mm)
    field(c, "b) Sl. No/ Certificate No.:", "NA", 112 * mm, y, 78 * mm, label_w=120)
    y -= 8 * mm
    field(c, "c) Company / TPA ID No.:", "NA", 18 * mm, y, 172 * mm)
    y -= 8 * mm
    field(c, "d) Name:", "Mr. Arjun Malhotra", 18 * mm, y, 172 * mm)
    y -= 8 * mm
    field(c, "e) Address:", "B-904, Palm Heights, Andheri East, Mumbai, Maharashtra, 400069", 18 * mm, y, 172 * mm)
    y -= 8 * mm
    field(c, "City:", "Mumbai", 18 * mm, y, 58 * mm, label_w=26)
    field(c, "State:", "Maharashtra", 102 * mm, y, 40 * mm, label_w=32)
    field(c, "Pincode:", "400069", 142 * mm, y, 48 * mm, label_w=42)
    y -= 8 * mm
    field(c, "Phone No.:", "9820012345", 18 * mm, y, 72 * mm, label_w=50)
    field(c, "Email ID:", "arjun.malhotra@example.com", 102 * mm, y, 88 * mm, label_w=44)

    y -= 12 * mm
    section_bar(c, "SECTION B - DETAILS OF INSURANCE HISTORY", y)
    y -= 10 * mm
    c.setFont("Helvetica", 10)
    c.drawString(18 * mm, y, "a) Currently covered by any other mediclaim health insurance:")
    checkbox(c, "Yes", False, 122 * mm, y + 1)
    checkbox(c, "No", True, 145 * mm, y + 1)
    y -= 8 * mm
    c.drawString(18 * mm, y, "b) Date of commencement of first insurance without break:")
    line(c, 97 * mm, y - 2, 190 * mm)
    c.drawString(98 * mm, y, "01-Jul-2026")
    y -= 8 * mm
    c.drawString(18 * mm, y, "c) Have you been hospitalized in the last four years")
    y -= 6 * mm
    c.drawString(18 * mm, y, "since inception of the contract:")
    line(c, 85 * mm, y - 2, 190 * mm)
    c.drawString(86 * mm, y, "Yes - 14-Feb-2025, uncontrolled diabetes")
    y -= 8 * mm
    c.drawString(18 * mm, y, "d) Previously covered by any other Mediclaim/Health insurance:")
    line(c, 97 * mm, y - 2, 190 * mm)
    c.drawString(98 * mm, y, "No")

    y -= 12 * mm
    section_bar(c, "SECTION C - DETAILS OF INSURED PERSON HOSPITALISED", y)
    y -= 10 * mm
    field(c, "a) Name:", "Mr. Arjun Malhotra", 18 * mm, y, 92 * mm)
    field(c, "d) Age:", "46 Years", 130 * mm, y, 60 * mm, label_w=34)
    y -= 8 * mm
    c.drawString(18 * mm, y, "b) Relationship to primary insured:")
    checkbox(c, "Self", True, 88 * mm, y + 1)
    checkbox(c, "Spouse", False, 112 * mm, y + 1)
    checkbox(c, "Child", False, 141 * mm, y + 1)
    y -= 8 * mm
    field(c, "c) Date of Birth:", "19-May-1980", 18 * mm, y, 92 * mm)
    checkbox(c, "Male", True, 130 * mm, y + 1)
    checkbox(c, "Female", False, 154 * mm, y + 1)
    y -= 8 * mm
    field(c, "e) Occupation:", "Self employed", 18 * mm, y, 92 * mm)
    field(c, "f) Mobile No.:", "9820012345", 130 * mm, y, 60 * mm, label_w=56)

    y -= 12 * mm
    section_bar(c, "SECTION D - DETAILS OF HOSPITALIZATION", y)
    y -= 10 * mm
    field(c, "a) Name of the Hospital where admitted:", "Lotus Multi Speciality Hospital, Mumbai", 18 * mm, y, 172 * mm, label_w=150)
    y -= 8 * mm
    field(c, "b) Room Category occupied:", "Single Occupancy", 18 * mm, y, 172 * mm, label_w=120)
    y -= 8 * mm
    c.drawString(18 * mm, y, "c) Hospitalisation due to:")
    checkbox(c, "Illness", True, 66 * mm, y + 1)
    checkbox(c, "Injury", False, 92 * mm, y + 1)
    checkbox(c, "Maternity", False, 116 * mm, y + 1)
    y -= 8 * mm
    field(c, "d) Date of disease first detected:", "15-Mar-2026", 18 * mm, y, 172 * mm, label_w=120)
    y -= 8 * mm
    field(c, "e) Date of admission:", "08-Aug-2026", 18 * mm, y, 82 * mm, label_w=88)
    field(c, "f) Time:", "08:30 PM", 112 * mm, y, 78 * mm, label_w=40)
    y -= 8 * mm
    field(c, "g) Date of discharge:", "10-Aug-2026", 18 * mm, y, 82 * mm, label_w=88)
    field(c, "h) Time:", "11:15 AM", 112 * mm, y, 78 * mm, label_w=40)
    y -= 8 * mm
    field(c, "i) Diagnosis:", "Diabetic nephropathy and uncontrolled Type 2 diabetes", 18 * mm, y, 172 * mm, label_w=60)
    y -= 8 * mm
    field(c, "j) Treating doctor's note:", "Patient had known diabetes before policy inception; advised regular treatment since 2025.", 18 * mm, y, 172 * mm, label_w=108)

    y -= 12 * mm
    section_bar(c, "SECTION E - DETAILS OF CLAIM", y)
    y -= 10 * mm
    field(c, "i) Pre-Hospitalization Expenses:", "Rs. 18,500", 18 * mm, y, 82 * mm, label_w=120)
    field(c, "ii) Hospitalization Expenses:", "Rs. 1,74,000", 112 * mm, y, 78 * mm, label_w=120)
    y -= 8 * mm
    field(c, "iii) Post-Hospitalization Expenses:", "Rs. 22,000", 18 * mm, y, 82 * mm, label_w=124)
    field(c, "iv) Total Claimed Amount:", "Rs. 2,14,500", 112 * mm, y, 78 * mm, label_w=96)

    y -= 12 * mm
    section_bar(c, "SECTION F - GROUNDS LIKELY TO CAUSE CLAIM REJECTION", y)
    y -= 10 * mm
    c.setFont("Helvetica", 10)
    reasons = [
        "1. Policy start date is 01-Jul-2026, but disease first detected date is 15-Mar-2026.",
        "2. Form explicitly states prior hospitalization in 2025 for uncontrolled diabetes.",
        "3. Treating doctor note says the condition existed before policy inception.",
        "4. Claim is for a pre-existing chronic illness with no waiting-period completion.",
        "5. Non-disclosure risk exists because prior history and present diagnosis materially overlap.",
    ]
    for reason in reasons:
        c.drawString(18 * mm, y, reason)
        y -= 6.5 * mm

    c.setFont("Helvetica", 7)
    c.drawString(
        18 * mm,
        9 * mm,
        "Placeholder values only. Synthetic claim form created for testing rejection logic without using private claimholder data.",
    )

    c.save()
    print(OUT)


if __name__ == "__main__":
    main()

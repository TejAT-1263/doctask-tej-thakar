from pathlib import Path

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer


ROOT = Path("/Users/tejthakar/Downloads/SuperDocs/doctask-tej-thakar")
INPUT_DIR = ROOT / "tmp-reject"
OUTPUT_DIR = ROOT / "output" / "pdf"


def build_styles():
    styles = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "DocTitle",
            parent=styles["Title"],
            fontName="Helvetica-Bold",
            fontSize=18,
            leading=22,
            textColor=HexColor("#15304a"),
            spaceAfter=8,
        ),
        "meta": ParagraphStyle(
            "Meta",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=9,
            leading=12,
            textColor=HexColor("#5b6470"),
            spaceAfter=10,
        ),
        "body": ParagraphStyle(
            "Body",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=11,
            leading=15,
            textColor=HexColor("#1f2933"),
            spaceAfter=5,
        ),
    }


def normalize_text(raw: str) -> list[str]:
    lines = []
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            lines.append("")
            continue
        line = (
            stripped.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )
        lines.append(line)
    return lines


def render_pdf(source_path: Path, title: str, subtitle: str):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    target = OUTPUT_DIR / f"{source_path.stem}.pdf"
    styles = build_styles()

    doc = SimpleDocTemplate(
        str(target),
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
    )

    story = [
        Paragraph(title, styles["title"]),
        Paragraph(subtitle, styles["meta"]),
        Spacer(1, 4),
    ]

    for line in normalize_text(source_path.read_text()):
        if not line:
            story.append(Spacer(1, 6))
        else:
            story.append(Paragraph(line, styles["body"]))

    doc.build(story)
    print(target)


def main():
    render_pdf(
        INPUT_DIR / "claim_form_reject.txt",
        "Filled Motor Insurance Claim Form",
        "Placeholder values only - synthetic Indian claim test document",
    )
    render_pdf(
        INPUT_DIR / "surveyor_report_reject.txt",
        "Surveyor Assessment Report",
        "Placeholder values only - synthetic Indian claim test document",
    )
    render_pdf(
        INPUT_DIR / "policy_schedule_reject.txt",
        "Private Car Policy Schedule",
        "Placeholder values only - synthetic Indian claim test document",
    )
    render_pdf(
        INPUT_DIR / "rejection_rulebook.txt",
        "Claims Review Rulebook",
        "Placeholder values only - synthetic Indian claim test document",
    )


if __name__ == "__main__":
    main()

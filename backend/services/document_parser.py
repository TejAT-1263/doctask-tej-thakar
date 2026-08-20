"""
Document parser service.
Converts uploaded files (PDF, DOCX, TXT) into raw text for the agent pipeline.
Fails loudly with clear error messages — never silently returns empty text.
"""
import io
import mimetypes
from typing import Tuple

try:
    import magic
except ImportError:
    magic = None


SUPPORTED_MIME_TYPES = {
    "application/pdf":       "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/msword":    "doc",
    "text/plain":            "txt",
    "text/html":             "html",
    "text/markdown":         "md",
}


def detect_mime(content: bytes) -> str:
    """Detect file MIME type from content bytes using libmagic."""
    if magic is None:
        return "application/octet-stream"
    try:
        return magic.from_buffer(content, mime=True)
    except Exception:
        return "application/octet-stream"


def parse_document(content: bytes, filename: str) -> Tuple[str, str]:
    """
    Parse a document file into raw text.

    Returns: (raw_text, mime_type)
    Raises: ValueError with clear message if parsing fails or format unsupported.
    """
    mime = detect_mime(content)
    if mime == "application/octet-stream":
        guessed, _ = mimetypes.guess_type(filename)
        mime = guessed or mime

    if mime == "application/pdf":
        return _parse_pdf(content), mime

    if mime in ("application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "application/msword"):
        return _parse_docx(content), mime

    if mime.startswith("text/"):
        try:
            return content.decode("utf-8", errors="replace"), mime
        except Exception as e:
            raise ValueError(f"Failed to decode text file '{filename}': {e}")

    raise ValueError(
        f"Unsupported file format for '{filename}' (detected: {mime}). "
        f"Supported: PDF, DOCX, TXT, HTML, Markdown."
    )


def _parse_pdf(content: bytes) -> str:
    """Extract text from PDF. Raises ValueError if PDF is encrypted or contains no text."""
    try:
        import pypdf
        reader = pypdf.PdfReader(io.BytesIO(content))

        if reader.is_encrypted:
            raise ValueError("PDF is encrypted — cannot extract text without a password.")

        pages_text = []
        for i, page in enumerate(reader.pages):
            text = page.extract_text() or ""
            if text.strip():
                pages_text.append(f"[Page {i+1}]\n{text}")

        if not pages_text:
            raise ValueError(
                "PDF contains no extractable text. "
                "This may be a scanned document (OCR not supported in v1). "
                "Please provide a text-based PDF."
            )

        return "\n\n".join(pages_text)

    except (ValueError, RuntimeError):
        raise
    except Exception as e:
        raise ValueError(f"PDF parsing failed: {e}")


def _parse_docx(content: bytes) -> str:
    """Extract text from DOCX, preserving paragraph structure."""
    try:
        from docx import Document
        doc = Document(io.BytesIO(content))

        paragraphs = []
        for para in doc.paragraphs:
            if para.text.strip():
                paragraphs.append(para.text)

        # Also extract table content
        for table in doc.tables:
            for row in table.rows:
                row_text = " | ".join(cell.text.strip() for cell in row.cells if cell.text.strip())
                if row_text:
                    paragraphs.append(f"[Table] {row_text}")

        if not paragraphs:
            raise ValueError("DOCX contains no extractable text.")

        return "\n\n".join(paragraphs)

    except (ValueError, RuntimeError):
        raise
    except Exception as e:
        raise ValueError(f"DOCX parsing failed: {e}")

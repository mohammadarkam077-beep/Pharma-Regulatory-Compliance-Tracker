from io import BytesIO


def extract_pdf_text(file_bytes):
    """Extract text from PDF bytes using pypdf."""
    try:
        from pypdf import PdfReader
    except ImportError:
        return {
            "success": False,
            "text": "",
            "page_count": 0,
            "message": "PDF parsing requires the pypdf package.",
        }

    try:
        reader = PdfReader(BytesIO(file_bytes))
        page_text = []

        for page_number, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            text = text.strip()
            if text:
                page_text.append(f"--- Page {page_number} ---\n{text}")

        extracted_text = "\n\n".join(page_text).strip()
        if not extracted_text:
            return {
                "success": True,
                "text": "",
                "page_count": len(reader.pages),
                "message": "No selectable text found. This PDF may be scanned or image-only.",
            }

        return {
            "success": True,
            "text": extracted_text,
            "page_count": len(reader.pages),
            "message": f"Extracted text from {len(reader.pages)} page(s).",
        }
    except Exception as exc:
        return {
            "success": False,
            "text": "",
            "page_count": 0,
            "message": f"Could not parse PDF: {exc}",
        }

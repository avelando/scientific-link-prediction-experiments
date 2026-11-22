"""Validate downloaded bytes as a usable scientific PDF.

Rejects HTML error/auth pages, truncated or non-PDF payloads, and files with no
extractable text layer (scanned images). Never runs OCR here. Pure function over
bytes so it is unit-testable without network.
"""

from __future__ import annotations

from dataclasses import dataclass

_PDF_MAGIC = b"%PDF-"
_HTML_MARKERS = (b"<!doctype html", b"<html", b"<head", b"<body")


@dataclass
class PdfValidation:
    is_valid: bool
    reason: str | None       # failure reason when not valid
    n_pages: int
    n_text_chars: int        # total extractable characters (0 => likely scanned)
    looks_scanned: bool


def validate_pdf_bytes(data: bytes | None, *, min_text_chars: int = 500) -> PdfValidation:
    """Validate raw bytes as an openable, text-bearing PDF."""
    if not data:
        return PdfValidation(False, "empty", 0, 0, False)

    head = data[:1024].lstrip()
    if head[:5] != _PDF_MAGIC:
        lowered = head.lower()
        if any(m in lowered for m in _HTML_MARKERS):
            return PdfValidation(False, "html_not_pdf", 0, 0, False)
        return PdfValidation(False, "bad_signature", 0, 0, False)

    try:
        import pymupdf

        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception as exc:  # corrupt / unreadable
        return PdfValidation(False, f"open_failed:{type(exc).__name__}", 0, 0, False)

    try:
        n_pages = doc.page_count
        text_chars = 0
        for page in doc:
            text_chars += len(page.get_text("text"))
            if text_chars >= min_text_chars:
                break
    finally:
        doc.close()

    if n_pages == 0:
        return PdfValidation(False, "no_pages", 0, 0, False)
    if text_chars < min_text_chars:
        # Openable but little/no text -> probably scanned images (no OCR here).
        return PdfValidation(False, "no_text_layer", n_pages, text_chars, True)
    return PdfValidation(True, None, n_pages, text_chars, False)

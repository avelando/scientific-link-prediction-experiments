"""Full-text extraction from validated PDFs.

Default extractor is PyMuPDF (direct text). GROBID (a separate Docker service that
parses PDFs into TEI/XML) is OPTIONAL: used only if a server URL is configured and
reachable. Section splitting is heuristic (regex on canonical headings) and separates
the reference list from the scientific body so citation titles do not leak in as
content. Anomalies (empty, too-short, repeated text, no text layer) are flagged.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger("slpe.pdf")

# Canonical section headings (lowercased match at line start).
_SECTION_PATTERNS = {
    "abstract": r"^\s*abstract\b",
    "introduction": r"^\s*(\d+\.?\s*)?introduction\b",
    "related_work": r"^\s*(\d+\.?\s*)?(related work|background|literature review)\b",
    "methods": r"^\s*(\d+\.?\s*)?(methods?|methodology|materials and methods|approach)\b",
    "results": r"^\s*(\d+\.?\s*)?(results|experiments?|evaluation|findings)\b",
    "discussion": r"^\s*(\d+\.?\s*)?discussion\b",
    "conclusion": r"^\s*(\d+\.?\s*)?(conclusions?|concluding remarks)\b",
    "limitations": r"^\s*(\d+\.?\s*)?limitations\b",
    "future_work": r"^\s*(\d+\.?\s*)?future work\b",
    "references": r"^\s*(references|bibliography)\s*$",
}
_COMPILED = {k: re.compile(v, re.IGNORECASE | re.MULTILINE) for k, v in _SECTION_PATTERNS.items()}


@dataclass
class ExtractionResult:
    ok: bool
    method: str
    n_pages: int
    n_chars: int
    full_text: str
    body_text: str                       # body WITHOUT the reference list
    sections: dict[str, str] = field(default_factory=dict)
    anomalies: list[str] = field(default_factory=list)


def _detect_anomalies(text: str, n_pages: int) -> list[str]:
    anomalies: list[str] = []
    if not text.strip():
        anomalies.append("empty_text")
        return anomalies
    if len(text) < 1000:
        anomalies.append("very_short")
    # Repeated-text heuristic: one line dominating the document.
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if lines:
        from collections import Counter
        most_common, count = Counter(lines).most_common(1)[0]
        if len(lines) > 50 and count / len(lines) > 0.3:
            anomalies.append("repeated_lines")
    return anomalies


def _split_sections(text: str) -> tuple[dict[str, str], str]:
    """Return (sections, body_without_references). Heuristic, best-effort."""
    hits = []
    for name, pat in _COMPILED.items():
        m = pat.search(text)
        if m:
            hits.append((m.start(), name))
    hits.sort()
    sections: dict[str, str] = {}
    for i, (start, name) in enumerate(hits):
        end = hits[i + 1][0] if i + 1 < len(hits) else len(text)
        sections[name] = text[start:end].strip()

    # Body excludes the references section (avoid cited-title leakage).
    ref_m = _COMPILED["references"].search(text)
    body = text[: ref_m.start()] if ref_m else text
    return sections, body.strip()


def extract_pymupdf(pdf_path: str) -> ExtractionResult:
    import pymupdf

    doc = pymupdf.open(pdf_path)
    try:
        n_pages = doc.page_count
        parts = [page.get_text("text") for page in doc]
    finally:
        doc.close()
    text = "\n".join(parts)
    sections, body = _split_sections(text)
    anomalies = _detect_anomalies(text, n_pages)
    return ExtractionResult(
        ok=not ("empty_text" in anomalies),
        method="pymupdf", n_pages=n_pages, n_chars=len(text),
        full_text=text, body_text=body, sections=sections, anomalies=anomalies,
    )


def grobid_available(grobid_url: str | None, timeout: float = 5.0) -> bool:
    """Check whether a GROBID server is reachable (isalive)."""
    if not grobid_url:
        return False
    try:
        import httpx

        r = httpx.get(grobid_url.rstrip("/") + "/api/isalive", timeout=timeout)
        return r.status_code == 200
    except Exception:
        return False


def extract_grobid(pdf_path: str, grobid_url: str, timeout: float = 120.0) -> ExtractionResult:
    """Extract structured text via a GROBID server (TEI). Falls back is caller's job."""
    import httpx

    url = grobid_url.rstrip("/") + "/api/processFulltextDocument"
    with open(pdf_path, "rb") as fh:
        r = httpx.post(url, files={"input": fh}, data={"consolidateHeader": "0"}, timeout=timeout)
    if r.status_code != 200:
        return ExtractionResult(False, "grobid", 0, 0, "", "", {}, [f"grobid_http_{r.status_code}"])
    tei = r.text
    # Minimal TEI handling: strip tags for a plain-text body (full TEI kept by caller).
    body = re.sub(r"<[^>]+>", " ", tei)
    body = re.sub(r"\s+", " ", body).strip()
    return ExtractionResult(
        ok=bool(body), method="grobid", n_pages=0, n_chars=len(body),
        full_text=tei, body_text=body, sections={}, anomalies=[] if body else ["empty_text"],
    )


def extract_text(pdf_path: str, *, grobid_url: str | None = None) -> ExtractionResult:
    """Extract full text, preferring GROBID when a server is reachable."""
    if grobid_url and grobid_available(grobid_url):
        try:
            return extract_grobid(pdf_path, grobid_url)
        except Exception as exc:
            logger.warning("GROBID failed (%s); falling back to PyMuPDF", exc)
    return extract_pymupdf(pdf_path)

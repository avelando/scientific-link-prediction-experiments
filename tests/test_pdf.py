"""Tests for the PDF pipeline: locations, validation, extraction, download funnel."""

from pathlib import Path

import httpx
import pymupdf

from slpe.config import PdfConfig
from slpe.pdf.download import PdfDownloader
from slpe.pdf.extract import extract_pymupdf
from slpe.pdf.locations import pdf_candidates
from slpe.pdf.validate import validate_pdf_bytes


def _make_pdf(text: str = "word " * 400) -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    # insert_textbox wraps within the rect so all the text is on-page/extractable.
    rect = pymupdf.Rect(50, 50, 550, 780)
    page.insert_textbox(rect, text, fontsize=9)
    data = doc.tobytes()
    doc.close()
    return data


# --- locations ------------------------------------------------------------

def test_pdf_candidates_priority_and_dedup():
    work = {
        "best_oa_location": {"pdf_url": "https://a/best.pdf", "license": "cc-by",
                             "version": "publishedVersion"},
        "locations": [
            {"pdf_url": "https://a/sub.pdf", "version": "submittedVersion"},
            {"pdf_url": "https://a/acc.pdf", "version": "acceptedVersion"},
            {"pdf_url": "https://a/best.pdf", "version": "publishedVersion"},  # dup
        ],
        "open_access": {"oa_url": "https://a/landing"},
    }
    cands = pdf_candidates(work)
    urls = [c.url for c in cands]
    assert urls[0] == "https://a/best.pdf"          # best_oa first
    assert "https://a/landing" not in urls          # oa_url NOT used (landing page)
    assert urls.count("https://a/best.pdf") == 1    # de-duplicated
    # accepted sorts before submitted among locations
    assert urls.index("https://a/acc.pdf") < urls.index("https://a/sub.pdf")
    assert all(c.is_direct_pdf for c in cands)       # only direct pdf_urls


def test_pdf_candidates_empty_when_no_oa():
    assert pdf_candidates({"open_access": {}, "locations": []}) == []


# --- validation -----------------------------------------------------------

def test_validate_real_pdf():
    v = validate_pdf_bytes(_make_pdf())
    assert v.is_valid and v.n_pages == 1 and v.n_text_chars >= 500


def test_validate_rejects_html():
    v = validate_pdf_bytes(b"<!DOCTYPE html><html><body>Access denied</body></html>")
    assert not v.is_valid and v.reason == "html_not_pdf"


def test_validate_rejects_non_pdf_and_empty():
    assert validate_pdf_bytes(b"garbage").reason == "bad_signature"
    assert validate_pdf_bytes(b"").reason == "empty"


def test_validate_flags_scanned_no_text():
    doc = pymupdf.open()
    doc.new_page()  # blank page, no text
    data = doc.tobytes()
    doc.close()
    v = validate_pdf_bytes(data, min_text_chars=500)
    assert not v.is_valid and v.reason == "no_text_layer" and v.looks_scanned


# --- extraction -----------------------------------------------------------

def test_extract_pymupdf_and_section_split(tmp_path):
    body = ("Introduction\nWe study X in depth. " + "content " * 100
            + "\nReferences\n[1] Someone, A cited title.\n")
    pdf = tmp_path / "p.pdf"
    pdf.write_bytes(_make_pdf(body))
    res = extract_pymupdf(str(pdf))
    assert res.ok and res.n_pages == 1
    assert "references" in res.sections
    # Body excludes the reference list (no cited-title leakage).
    assert "cited title" not in res.body_text


# --- download funnel ------------------------------------------------------

def _cfg(tmp_path) -> PdfConfig:
    return PdfConfig(dir=tmp_path / "pdfs", timeout_seconds=5, max_retries=1,
                     max_bytes_per_file=10_000_000, per_host_delay_seconds=0.0,
                     min_text_chars=500, allow_content_api=False, grobid_url=None,
                     max_pdfs=None, max_total_bytes=None)


def _downloader(cfg, handler):
    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
    return PdfDownloader(config=cfg, _client=client)


def test_acquire_tries_candidates_until_valid(tmp_path):
    good = _make_pdf()

    def handler(request):
        if request.url.path.endswith("bad.pdf"):
            return httpx.Response(404)
        if request.url.path.endswith("html.pdf"):
            return httpx.Response(200, content=b"<html>error</html>")
        return httpx.Response(200, content=good)

    from slpe.pdf.locations import PdfCandidate
    cands = [
        PdfCandidate("https://h/bad.pdf", "loc", None, None, None, True),
        PdfCandidate("https://h/html.pdf", "loc", None, None, None, True),
        PdfCandidate("https://h/good.pdf", "best", "cc-by", "publishedVersion", "journal", True),
    ]
    with _downloader(_cfg(tmp_path), handler) as d:
        res = d.acquire("W1", cands)
    assert res.acquired and res.license == "cc-by"
    assert Path(res.pdf_path).exists()
    assert len(res.attempts) == 3  # tried all three in order
    assert res.attempts[0].failure_reason == "http_404"
    assert res.attempts[1].failure_reason == "html_not_pdf"


def test_acquire_reuses_local_pdf_even_if_redownload_fails(tmp_path):
    good = _make_pdf()
    from slpe.pdf.locations import PdfCandidate
    cands = [PdfCandidate("https://h/good.pdf", "best", "cc-by", "publishedVersion", "journal", True)]

    # First run downloads and writes W1.pdf + sidecar.
    with _downloader(_cfg(tmp_path), lambda req: httpx.Response(200, content=good)) as d:
        r1 = d.acquire("W1", cands)
    assert r1.acquired and r1.outcome == "downloaded"

    # Second run: every download 404s, but the valid local PDF must be REUSED.
    with _downloader(_cfg(tmp_path), lambda req: httpx.Response(404)) as d:
        r2 = d.acquire("W1", cands)
    assert r2.acquired and r2.outcome == "reused"
    assert r2.attempts == []  # no network attempts — served locally


def test_acquire_reports_failure_when_none_valid(tmp_path):
    def handler(request):
        return httpx.Response(403)

    from slpe.pdf.locations import PdfCandidate
    cands = [PdfCandidate("https://h/x.pdf", "loc", None, None, None, True)]
    with _downloader(_cfg(tmp_path), handler) as d:
        res = d.acquire("W2", cands)
    assert not res.acquired and res.outcome == "failed"
    assert res.failure_reason == "no_valid_candidate"
    assert res.attempts[0].http_status == 403

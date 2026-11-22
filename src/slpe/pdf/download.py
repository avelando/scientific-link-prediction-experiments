"""Download OA PDFs from metadata-provided URLs, with limits and validation.

Respects HTTP status codes (no retry on 403/404; backoff on 429/5xx), caps bytes
per file, and applies a per-host politeness delay. Never circumvents paywalls,
authentication or technical blocks. Each attempt returns a structured record with
status, size, SHA-256 and a failure reason, so the collection funnel is auditable.
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import asdict, dataclass, field
from urllib.parse import urlparse

import httpx

from slpe.config import PdfConfig
from slpe.pdf.locations import PdfCandidate
from slpe.pdf.validate import PdfValidation, validate_pdf_bytes

logger = logging.getLogger("slpe.pdf")

_NO_RETRY_STATUS = {401, 403, 404, 410}
_RETRY_STATUS = {429, 500, 502, 503, 504}


@dataclass
class DownloadAttempt:
    url: str
    source: str
    ok: bool
    http_status: int | None
    content_type: str | None
    n_bytes: int
    sha256: str | None
    failure_reason: str | None
    validation: dict | None  # PdfValidation as dict when a body was fetched


@dataclass
class AcquisitionResult:
    work_id: str
    acquired: bool
    outcome: str          # "reused" | "downloaded" | "failed"
    pdf_path: str | None
    sha256: str | None
    license: str | None
    version: str | None
    n_pages: int
    n_text_chars: int
    attempts: list[DownloadAttempt] = field(default_factory=list)
    failure_reason: str | None = None


@dataclass
class PdfDownloader:
    config: PdfConfig
    contact: str | None = None
    _client: httpx.Client | None = None
    _last_host_hit: dict[str, float] = field(default_factory=dict)
    total_bytes: int = 0

    @classmethod
    def create(cls, config: PdfConfig, contact: str | None = None) -> PdfDownloader:
        ua = "scientific-link-prediction-experiments/0.1 (research)"
        if contact:
            ua += f" mailto:{contact}"
        client = httpx.Client(timeout=config.timeout_seconds, follow_redirects=True,
                              headers={"User-Agent": ua, "Accept": "application/pdf,*/*"})
        return cls(config=config, contact=contact, _client=client)

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _politeness(self, url: str) -> None:
        host = urlparse(url).netloc
        last = self._last_host_hit.get(host)
        if last is not None:
            wait = self.config.per_host_delay_seconds - (time.monotonic() - last)
            if wait > 0:
                time.sleep(wait)
        self._last_host_hit[host] = time.monotonic()

    def _download_bytes(
        self, url: str
    ) -> tuple[bytes | None, int | None, str | None, str | None]:
        """Stream a URL into bytes with a size cap.

        Returns (data, http_status, failure_reason, content_type).
        """
        assert self._client is not None
        backoff = 1.0
        for attempt in range(1, self.config.max_retries + 2):
            self._politeness(url)
            try:
                with self._client.stream("GET", url) as resp:
                    status = resp.status_code
                    ctype = resp.headers.get("content-type")
                    if status in _NO_RETRY_STATUS:
                        return None, status, f"http_{status}", ctype
                    if status in _RETRY_STATUS:
                        if attempt <= self.config.max_retries:
                            time.sleep(backoff)
                            backoff = min(backoff * 2, 30.0)
                            continue
                        return None, status, f"http_{status}", ctype
                    if status != 200:
                        return None, status, f"http_{status}", ctype
                    chunks = bytearray()
                    for chunk in resp.iter_bytes():
                        chunks.extend(chunk)
                        if len(chunks) > self.config.max_bytes_per_file:
                            return None, status, "exceeds_max_bytes", ctype
                    return bytes(chunks), status, None, ctype
            except httpx.RequestError as exc:
                if attempt <= self.config.max_retries:
                    time.sleep(backoff)
                    backoff = min(backoff * 2, 30.0)
                    continue
                return None, None, f"request_error:{type(exc).__name__}", None
        return None, None, "exhausted", None

    def _sidecar_path(self, work_id: str) -> Path:
        return self.config.dir / f"{work_id}.json"

    def _reuse_local(self, work_id: str) -> AcquisitionResult | None:
        """Return a 'reused' result if a validated local PDF already exists."""
        pdf_path = self.config.dir / f"{work_id}.pdf"
        if not pdf_path.exists():
            return None
        side = self._sidecar_path(work_id)
        try:
            data = pdf_path.read_bytes()
        except OSError:
            return None
        sha = hashlib.sha256(data).hexdigest()
        # Trust a sidecar that matches the file hash; otherwise re-validate.
        if side.exists():
            try:
                import json
                rec = json.loads(side.read_text(encoding="utf-8"))
                if rec.get("sha256") == sha and rec.get("is_valid"):
                    return AcquisitionResult(
                        work_id, True, "reused", str(pdf_path), sha,
                        rec.get("license"), rec.get("version"),
                        int(rec.get("n_pages", 0)), int(rec.get("n_text_chars", 0)))
            except (OSError, ValueError):
                pass
        val = validate_pdf_bytes(data, min_text_chars=self.config.min_text_chars)
        if val.is_valid:
            self._write_sidecar(work_id, sha, None, None, val)
            return AcquisitionResult(work_id, True, "reused", str(pdf_path), sha,
                                     None, None, val.n_pages, val.n_text_chars)
        return None

    def _write_sidecar(self, work_id, sha, license_, version, val: PdfValidation) -> None:
        import json
        rec = {"sha256": sha, "is_valid": val.is_valid, "license": license_,
               "version": version, "n_pages": val.n_pages, "n_text_chars": val.n_text_chars,
               "validated_utc": __import__("datetime").datetime.now(
                   __import__("datetime").timezone.utc).isoformat()}
        self._sidecar_path(work_id).write_text(json.dumps(rec), encoding="utf-8")

    def acquire(self, work_id: str, candidates: list[PdfCandidate]) -> AcquisitionResult:
        """Return a validated PDF, reusing a local copy when present.

        Order: (1) reuse a validated local PDF if it exists (a failed re-download
        never discards a good local file); (2) otherwise try each candidate URL in
        order and return the first that downloads AND validates.
        """
        reused = self._reuse_local(work_id)
        if reused is not None:
            return reused

        result = AcquisitionResult(
            work_id=work_id, acquired=False, outcome="failed", pdf_path=None, sha256=None,
            license=None, version=None, n_pages=0, n_text_chars=0,
        )
        if self.config.max_total_bytes is not None and self.total_bytes >= self.config.max_total_bytes:
            result.failure_reason = "byte_budget_exhausted"
            return result

        for cand in candidates:
            data, status, reason, ctype = self._download_bytes(cand.url)
            if data is None:
                result.attempts.append(DownloadAttempt(
                    cand.url, cand.source, False, status, ctype, 0, None, reason, None))
                continue
            self.total_bytes += len(data)
            val: PdfValidation = validate_pdf_bytes(data, min_text_chars=self.config.min_text_chars)
            sha = hashlib.sha256(data).hexdigest()
            attempt = DownloadAttempt(
                cand.url, cand.source, val.is_valid, status, ctype, len(data), sha,
                None if val.is_valid else val.reason, asdict(val))
            result.attempts.append(attempt)
            if val.is_valid:
                self.config.dir.mkdir(parents=True, exist_ok=True)
                path = self.config.dir / f"{work_id}.pdf"
                path.write_bytes(data)
                self._write_sidecar(work_id, sha, cand.license, cand.version, val)
                result.acquired = True
                result.outcome = "downloaded"
                result.pdf_path = str(path)
                result.sha256 = sha
                result.license = cand.license
                result.version = cand.version
                result.n_pages = val.n_pages
                result.n_text_chars = val.n_text_chars
                return result
        if not result.failure_reason:
            result.failure_reason = "no_valid_candidate" if candidates else "no_pdf_url"
        return result

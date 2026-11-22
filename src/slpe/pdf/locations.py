"""Extract ordered candidate OA PDF sources from an OpenAlex work.

Priority (most authoritative first):
    1. best_oa_location.pdf_url
    2. any locations[].pdf_url (preferring published, then accepted, then others)

We deliberately do NOT use ``open_access.oa_url``: it frequently points at an HTML
landing page rather than a PDF, and treating it as a PDF produces false downloads.
Only DIRECT ``pdf_url`` fields are used. Each candidate records license, version and
host type so downstream code can honour redistribution limits and prefer trustworthy,
text-mining-friendly sources.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Version preference: published > accepted > submitted/other.
_VERSION_RANK = {"publishedVersion": 0, "acceptedVersion": 1, "submittedVersion": 2}


@dataclass(frozen=True)
class PdfCandidate:
    url: str
    source: str          # where in the metadata it came from
    license: str | None
    version: str | None
    host_type: str | None  # journal / repository / etc.
    is_direct_pdf: bool    # True if it came from a pdf_url field


def _loc_fields(loc: dict[str, Any]) -> tuple[str | None, str | None, str | None]:
    lic = loc.get("license")
    ver = loc.get("version")
    host = (loc.get("source") or {}).get("type") if isinstance(loc.get("source"), dict) else None
    return lic, ver, host


def pdf_candidates(work: dict[str, Any]) -> list[PdfCandidate]:
    """Return ordered, de-duplicated PDF candidates for a work."""
    candidates: list[PdfCandidate] = []
    seen: set[str] = set()

    def add(url: str | None, source: str, loc: dict[str, Any] | None, direct: bool):
        if not url or url in seen:
            return
        seen.add(url)
        lic, ver, host = _loc_fields(loc or {})
        candidates.append(PdfCandidate(url, source, lic, ver, host, direct))

    best = work.get("best_oa_location") or {}
    add(best.get("pdf_url"), "best_oa_location.pdf_url", best, True)

    locations = [loc for loc in (work.get("locations") or []) if isinstance(loc, dict)]
    locations.sort(key=lambda loc: _VERSION_RANK.get(loc.get("version"), 9))
    for loc in locations:
        add(loc.get("pdf_url"), "locations.pdf_url", loc, True)

    # open_access.oa_url is intentionally excluded (it is often a landing page).
    return candidates

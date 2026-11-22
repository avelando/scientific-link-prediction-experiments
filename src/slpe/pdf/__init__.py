"""Open-access PDF acquisition, validation and full-text extraction (Stage 2, Phase B).

Free-only strategy: PDFs are pulled from the open-access locations OpenAlex already
exposes in metadata (``best_oa_location.pdf_url`` -> ``locations[].pdf_url`` ->
``open_access.oa_url``). The paid OpenAlex *content* API (``content.openalex.org``)
is NOT used unless explicitly enabled. Downloads respect HTTP status codes, rate
limits and per-host politeness; paywalls/auth/blocks are never circumvented. Access
to read OA is not treated as permission to redistribute PDFs — licenses are recorded.
"""

WORKS_PDF_SELECT = (
    "id,doi,title,publication_year,primary_topic,type,language,"
    "open_access,best_oa_location,locations"
)

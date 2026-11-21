# Audit response matrix — Stage 1 remediation

Each row records: the audit finding, the affected file, whether it was **confirmed**
against the current code, the root cause, the scientific/technical impact, the fix,
and the test that verifies it. Verdicts: **Confirmed**, **Partially confirmed**,
**Not a defect** (behaviour is correct or already handled).

| # | Finding | File | Verdict | Cause | Impact | Fix | Test |
|---|---|---|---|---|---|---|---|
| C1 | `.env` with real key shipped in ZIP | `.env` | **Confirmed** (untracked but present in folder) | Folder zipped including untracked files | Credential exposure | Advise rotation; keep gitignore; add packaging guard; sanitize logs; dotenv loads env only | `test_security.py` (gitignore + redaction) |
| C2 | httpx INFO logs print full URLs incl. `api_key` | `cli/*.py` | **Confirmed** | `basicConfig(INFO)` enables httpx logger | Key/mailto leak to log files | Redacting log filter; raise httpx logger to WARNING | `test_security.py::test_redaction` |
| C3 | No predictive experiments | — | **Confirmed / by design** | Stage 1 only | H1/H2/H3 untested | Out of scope now; stated clearly in reports | n/a |
| C4 | Counts include all document types | `fields.py` | **Confirmed** | Filter lacked `type:` | CS over-counted (conf-papers ~= articles) → biased corpus | Configurable `corpus.types`; sensitivity vs `+conference-paper` | `test_characterization.py::test_type_filter` |
| C5 | Subfield count as eliminatory gate | `eligibility.py`, `default.yaml` | **Confirmed** | `min_subfield_diversity` hard gate | Excludes Physics, Chemistry, Materials despite coverage | Drop as gate; keep descriptive; add normalized entropy; sensitivity table | `test_eligibility.py` |
| C5b | 6 eligible; 14 if subfield gate removed | CSVs | **Confirmed** (reproduced offline) | — | Shows gate dominates selection | Sensitivity analysis module reproduces both | `test_sensitivity.py` |
| C6 | `has_references:true` required for "eligible" conflates corpora | `fields.py` | **Confirmed** | Single eligible definition | Would drop no-reference works from semantic corpus | Three levels: semantic / bibliometric / DI-candidate | `test_characterization.py::test_three_levels` |
| C7 | Weighted (Brito-style) field attribution missing | `fields.py` | **Confirmed** | Only `primary_topic.field.id` | No multidisciplinarity view; selection less defensible | New `weighting.py`: primary vs `topics[].score`-weighted | `test_weighting.py` |
| C8 | `english_abstract_fraction` is a metadata proxy | `fields.py` | **Confirmed** | Counts flags, not reconstructed text | Overstates usable-text coverage | Relabel as metadata proxy; add sampling validator with Wilson CIs | `test_quality_sampling.py` |
| C9 | Volume ≠ compute feasibility; novelty needs full history not random sample | reports | **Confirmed / scope note** | — | Risk of false "novelty" from sampling | Documented; sampling design deferred to Stage 2 with warning | n/a (doc) |
| C10 | 2017/2019/2021 violate train/val/test for DI | `config.py` | **Confirmed / correct** | Overlap with Δe+Δd | Fine as retrospective link eval, not DI splits | Validator already flags; message clarified | `test_config.py` (existing) |
| C11 | Cache has no provenance/TTL; manifest no hashes | `client.py`, `manifest.py` | **Confirmed** | Body-only cache; run-time snapshot | Can mix collection dates; non-reproducible | Cache envelope (fetched_utc, Date hdr, query id, collector ver); manifest adds git commit + artifact hashes; TTL/refresh | `test_client.py::test_cache_envelope` |
| C12 | Checkpoint not transactional | `client.py` | **Partially confirmed** | Cursor saved after page yielded, not after consumer persists | Resume may skip rows if consumer crashes mid-page | Document contract; add page-level callback persisted before cursor advance; bind checkpoint to query id | `test_client.py::test_checkpoint_query_binding` |
| M13 | `.env` not auto-loaded | `config.py` | **Confirmed** | Reads `os.environ` only | README step insufficient | Optional `python-dotenv` load | `test_config.py::test_dotenv` |
| M14 | `--limit` limits after collection | `cli/characterize_fields.py` | **Confirmed** | Slices after full sweep | Smoke test still hits 26 fields | Limit field list before loop | `test_cli.py::test_limit` |
| M15 | Temporal validator misses L vs history_start | `config.py` | **Confirmed** | Only checks positivity/order | Misconfig undetected | Add `L == cut-history_start+1` and emergence checks | `test_config.py` |
| M16 | `group_by` truncation unchecked | `client.py` | **Confirmed (latent)** | 200-bucket cap unverified | OK now (<200), risky later | Warn if buckets == per-page cap | `test_client.py::test_groupby_truncation_warns` |
| M17 | `reconstruct_abstract` silently overwrites collisions | `abstracts.py` | **Confirmed** | position→token last-writer | Masks malformed indices | Count collisions/invalid; optional strict mode; diagnostics | `test_abstracts.py` (new cases) |
| M18 | `max_tokens` applied after full build | `abstracts.py` | **Confirmed (minor)** | Cap on output not input | Memory on pathological index | Early size guard on total positions | `test_abstracts.py::test_input_cap` |
| M19 | Chart color conflates eligibility & candidacy | `report.py` | **Confirmed** | Candidate color overrides | Misleading figure | Color=eligibility, marker/edge=candidacy | visual; smoke test renders |
| M20 | Report CLI imports viz but it's optional | `pyproject.toml`, `report.py` | **Confirmed** | matplotlib in `viz` extra only | `pip install -e ".[dev]"` lacks it | Move matplotlib to core deps; README fixed | import test |
| M21 | No lockfile | `pyproject.toml` | **Confirmed / accepted** | — | Replication drift | Document `pip freeze` lock step; manifest records versions | n/a |
| M22 | Traceability matrix mixes project origin vs implemented | `docs/traceability_matrix.md` | **Confirmed** | Status P/E/L = requirement origin | Reader can't tell implemented from planned | Add `implementation_status` column | n/a |
| M23 | Report may mix new numbers with old manifest time | `cli/report_characterization.py` | **Confirmed** | Reads old manifest timestamp, may re-query | Provenance mismatch | Report strictly from frozen artifacts; fail if absent | `test_report_provenance.py` |

Scope held to Stage 1 (no concept extraction, networks, link prediction, or
disruption computation), per the request.

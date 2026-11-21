# Stage 1 — preliminary results: field characterization & eligibility

_Data snapshot (UTC): 2026-11-21T19:48:02.350457+00:00. Source: OpenAlex aggregate queries._

> Feasibility indicators only. Eligibility is decided on data quality, never on model accuracy. No predictive claim is made here.

## Summary

- Fields characterized: **26** of 26.
- Eligible under current thresholds: **6**.
- Project candidates — Computer Science (17): eligible, Medicine (27): eligible, Physics and Astronomy (31): INELIGIBLE.

## Eligible fields, ranked by min eligible volume per cut

| field | id | domain | min eligible/cut | en-abstract | with-refs | subfields |
|---|---|---|---:|---:|---:|---:|
| Medicine | 27 | Health Sciences | 2,140,118 | 0.51 | 0.71 | 42 |
| Engineering | 22 | Physical Sciences | 1,607,257 | 0.56 | 0.75 | 16 |
| Computer Science | 17 | Physical Sciences | 895,392 | 0.61 | 0.79 | 11 |
| Agricultural and Biological Sciences | 11 | Life Sciences | 575,348 | 0.53 | 0.57 | 11 |
| Environmental Science | 23 | Physical Sciences | 421,098 | 0.50 | 0.56 | 11 |
| Mathematics | 26 | Physical Sciences | 252,176 | 0.57 | 0.81 | 10 |

## Candidate fields flagged ineligible (criterion detail)

- **Physics and Astronomy (31)**: subfield diversity 8 < 10

> These thresholds are development placeholders (see config `characterization.eligibility`). A flagged project candidate is reported, not silently dropped; the criterion should be reviewed before the main study.

## Figures

- Eligible volume per cut (all fields): `figures/stage1_eligible_volume.png`
- Documentary coverage scatter: `figures/stage1_coverage_scatter.png`
- Yearly eligible volume (candidates + top eligible): `figures/stage1_candidate_years.png`

## Full tables

- Per-field indicators: `field_characterization.csv`
- Eligibility verdicts: `field_eligibility.csv`
- Run manifest: `field_characterization.manifest.json`

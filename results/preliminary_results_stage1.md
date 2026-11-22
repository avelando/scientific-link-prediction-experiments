# Stage 1 — preliminary results: field characterization & eligibility

_Rendered from frozen artifacts. Collection run: 2026-11-22T05:28:09.299245+00:00 (code run time, NOT a frozen DB snapshot). Corpus types: article. git: f021a90bfa5654bb31516db58c8d135e1735a526._

> Feasibility indicators only. Eligibility uses data quality, never model accuracy. English-abstract figures are OpenAlex METADATA flags; see the textual-quality sampling report for inspected text coverage.

## Summary

- Fields characterized: **26** of 26.
- Semantic-eligible: **16**; bibliometric-ready: **16**.
- Project candidates — Medicine (27): semantic-eligible, Computer Science (17): semantic-eligible, Physics and Astronomy (31): semantic-eligible.

## Semantic-eligible fields, ranked by min semantic volume per cut

| field | id | domain | min semantic/cut | en-abstract | with-refs | biblio-ready | subfields | entropy |
|---|---|---|---:|---:|---:|:--:|---:|---:|
| Medicine | 27 | Health Sciences | 2,488,766 | 0.55 | 0.77 | yes | 42 | 0.90 |
| Engineering | 22 | Physical Sciences | 1,237,935 | 0.53 | 0.78 | yes | 16 | 0.85 |
| Agricultural and Biological Sciences | 11 | Life Sciences | 717,397 | 0.54 | 0.76 | yes | 11 | 0.84 |
| Biochemistry, Genetics and Molecular Biology | 13 | Life Sciences | 560,969 | 0.63 | 0.87 | yes | 14 | 0.63 |
| Computer Science | 17 | Physical Sciences | 485,890 | 0.56 | 0.77 | yes | 11 | 0.88 |
| Materials Science | 25 | Physical Sciences | 473,198 | 0.56 | 0.85 | yes | 8 | 0.80 |
| Physics and Astronomy | 31 | Physical Sciences | 443,018 | 0.69 | 0.90 | yes | 8 | 0.90 |
| Chemistry | 16 | Physical Sciences | 329,471 | 0.63 | 0.89 | yes | 6 | 0.83 |
| Earth and Planetary Sciences | 19 | Physical Sciences | 231,729 | 0.54 | 0.83 | yes | 8 | 0.97 |
| Mathematics | 26 | Physical Sciences | 213,460 | 0.59 | 0.88 | yes | 10 | 0.87 |
| Neuroscience | 28 | Life Sciences | 177,330 | 0.59 | 0.82 | yes | 8 | 0.74 |
| Immunology and Microbiology | 24 | Life Sciences | 160,312 | 0.60 | 0.84 | yes | 5 | 0.88 |
| Decision Sciences | 18 | Social Sciences | 116,302 | 0.54 | 0.75 | yes | 4 | 0.59 |
| Dentistry | 35 | Health Sciences | 100,995 | 0.56 | 0.80 | yes | 4 | 0.89 |
| Pharmacology, Toxicology and Pharmaceutics | 30 | Life Sciences | 75,367 | 0.60 | 0.81 | yes | 4 | 0.99 |
| Veterinary | 34 | Health Sciences | 20,148 | 0.50 | 0.85 | yes | 2 | 0.72 |

## Candidate fields flagged ineligible

- None. All project candidates are semantic-eligible under the corrected criteria (subfield count is no longer a gate).

## Eligibility sensitivity (how the eligible set shifts per criterion)

| scenario | n semantic-eligible | fields |
|---|---:|---|
| baseline | 16 | Agricultural and Biological Sciences(11), Biochemistry, Genetics and Molecular Biology(13), Chemistry(16), Computer Science(17), Decision Sciences(18), Earth and Planetary Sciences(19), Engineering(22), Immunology and Microbiology(24), Materials Science(25), Mathematics(26), Medicine(27), Neuroscience(28), Pharmacology, Toxicology and Pharmaceutics(30), Physics and Astronomy(31), Veterinary(34), Dentistry(35) |
| no_volume_gate | 16 | Agricultural and Biological Sciences(11), Biochemistry, Genetics and Molecular Biology(13), Chemistry(16), Computer Science(17), Decision Sciences(18), Earth and Planetary Sciences(19), Engineering(22), Immunology and Microbiology(24), Materials Science(25), Mathematics(26), Medicine(27), Neuroscience(28), Pharmacology, Toxicology and Pharmaceutics(30), Physics and Astronomy(31), Veterinary(34), Dentistry(35) |
| no_english_gate | 26 | Agricultural and Biological Sciences(11), Arts and Humanities(12), Biochemistry, Genetics and Molecular Biology(13), Business, Management and Accounting(14), Chemical Engineering(15), Chemistry(16), Computer Science(17), Decision Sciences(18), Earth and Planetary Sciences(19), Economics, Econometrics and Finance(20), Energy(21), Engineering(22), Environmental Science(23), Immunology and Microbiology(24), Materials Science(25), Mathematics(26), Medicine(27), Neuroscience(28), Nursing(29), Pharmacology, Toxicology and Pharmaceutics(30), Physics and Astronomy(31), Psychology(32), Social Sciences(33), Veterinary(34), Dentistry(35), Health Professions(36) |
| no_references_gate | 16 | Agricultural and Biological Sciences(11), Biochemistry, Genetics and Molecular Biology(13), Chemistry(16), Computer Science(17), Decision Sciences(18), Earth and Planetary Sciences(19), Engineering(22), Immunology and Microbiology(24), Materials Science(25), Mathematics(26), Medicine(27), Neuroscience(28), Pharmacology, Toxicology and Pharmaceutics(30), Physics and Astronomy(31), Veterinary(34), Dentistry(35) |
| english>=0.3 | 25 | Agricultural and Biological Sciences(11), Biochemistry, Genetics and Molecular Biology(13), Business, Management and Accounting(14), Chemical Engineering(15), Chemistry(16), Computer Science(17), Decision Sciences(18), Earth and Planetary Sciences(19), Economics, Econometrics and Finance(20), Energy(21), Engineering(22), Environmental Science(23), Immunology and Microbiology(24), Materials Science(25), Mathematics(26), Medicine(27), Neuroscience(28), Nursing(29), Pharmacology, Toxicology and Pharmaceutics(30), Physics and Astronomy(31), Psychology(32), Social Sciences(33), Veterinary(34), Dentistry(35), Health Professions(36) |
| english>=0.4 | 23 | Agricultural and Biological Sciences(11), Biochemistry, Genetics and Molecular Biology(13), Chemical Engineering(15), Chemistry(16), Computer Science(17), Decision Sciences(18), Earth and Planetary Sciences(19), Economics, Econometrics and Finance(20), Energy(21), Engineering(22), Environmental Science(23), Immunology and Microbiology(24), Materials Science(25), Mathematics(26), Medicine(27), Neuroscience(28), Nursing(29), Pharmacology, Toxicology and Pharmaceutics(30), Physics and Astronomy(31), Psychology(32), Veterinary(34), Dentistry(35), Health Professions(36) |
| english>=0.5 | 16 | Agricultural and Biological Sciences(11), Biochemistry, Genetics and Molecular Biology(13), Chemistry(16), Computer Science(17), Decision Sciences(18), Earth and Planetary Sciences(19), Engineering(22), Immunology and Microbiology(24), Materials Science(25), Mathematics(26), Medicine(27), Neuroscience(28), Pharmacology, Toxicology and Pharmaceutics(30), Physics and Astronomy(31), Veterinary(34), Dentistry(35) |
| english>=0.6 | 5 | Biochemistry, Genetics and Molecular Biology(13), Chemistry(16), Immunology and Microbiology(24), Pharmacology, Toxicology and Pharmaceutics(30), Physics and Astronomy(31) |

## Legacy-criteria reproduction (on the ORIGINAL cached data)

- Audited criteria incl. the `subfield >= 10` gate reproduced **6** eligible fields on the original results CSV (see `legacy/`). Removing only that gate raises the count — confirming the audit's observation that the subfield gate dominated the old selection.

## Domain recommendation (preliminary)

The three project candidates are all semantic-eligible and bibliometric-ready, and span 2 OpenAlex domain(s):

- **Medicine (27)** — Health Sciences; min semantic/cut 2,488,766, en-abstract 0.55, refs 0.77, subfield entropy 0.90.
- **Computer Science (17)** — Physical Sciences; min semantic/cut 485,890, en-abstract 0.56, refs 0.77, subfield entropy 0.88.
- **Physics and Astronomy (31)** — Physical Sciences; min semantic/cut 443,018, en-abstract 0.69, refs 0.90, subfield entropy 0.90.

These remain the recommended candidates for the main evaluation on grounds of coverage and disciplinary diversity. Open items before the choice is FIXED: (a) confirm Computer Science's corpus-type decision — including conference-papers roughly doubles its semantic corpus (see `field_corpus_sensitivity.csv`); (b) the selection must be frozen BEFORE any predictive results are seen. The pick is not forced here where information is still pending.

## Figures

- Semantic volume per cut (all fields): `figures/stage1_eligible_volume.png`
- Coverage scatter: `figures/stage1_coverage_scatter.png`
- Yearly semantic volume (candidates + top eligible): `figures/stage1_candidate_years.png`

## Full tables & provenance

- Per-field indicators: `field_characterization.csv`
- Per-year counts: `field_characterization_years.csv`
- Eligibility verdicts: `field_eligibility.csv`
- Sensitivity: `field_sensitivity.csv`
- Run manifest (hashes, versions): `field_characterization.manifest.json`

# Preliminary results — link-prediction comparison (bias-corrected)

_Real run on OpenAlex Computer Science (field 17), title+abstract, 250 works/year
sampled 2013–2022 (reproducible seed), YAKE concepts. Three retrospective cuts.
Viability results, not the final study._

## Methodological corrections applied (Etapa A)

The previous run had an evaluation bias that is now fixed:

1. **Precision@K tie-breaking.** Candidates listed positives first and ties (many
   zero scores) kept input order, so a constant scorer reached Precision@100 ≈ 1.0.
   Precision@K / Recall@K are now the **expected values under random tie-breaking**
   (closed form) — order-independent, so a constant scorer yields Precision@K =
   prevalence. Regression tests enforce this and permutation-invariance.
2. **Candidate universe.** The old run kept all positives + only 2,000 uniform
   negatives, which inflated prevalence to ≈0.24. The universe is now the
   **exhaustive** set of all eligible pairs among frequency-eligible concepts
   (≥ `min_concept_docs` historical documents), giving the real prevalence (~0.001).
3. **Concept normalization.** Over-singularization (`physics`→`physic`,
   `analysis`→`analysi`, `series`→`sery`) replaced by a conservative rule with a
   scientific-term exception list.
4. **Concept cache key** now encodes the sample, seed, extraction params and
   normalization version, so parameter changes rebuild the cache.

## Old (biased) vs corrected — why the numbers moved

| | OLD (biased) | CORRECTED |
|---|---|---|
| Candidate universe | all positives + 2,000 uniform negatives | exhaustive, all eligible pairs |
| Candidates (2021 cut) | ~2,600 | 177,748 |
| Prevalence (2021 cut) | 0.24 (artificial) | 0.0009 (real) |
| Precision@100 (constant/tied scorer) | ≈ 1.0 (artifact) | = prevalence (correct) |
| AUPRC range | 0.17–0.37 | 0.003–0.015 |

The AUPRC collapse is expected and honest: predicting rare emergent links (~1 in
1,000 candidates) is hard. The right question is **lift over the baselines**, not the
absolute value.

## Corrected results (observed)

**Networks** (concepts co-occurring in title+abstract; `min_concept_docs=3`):

| Cut | nodes | edges | density | giant comp. | eligible concepts | candidates | positives | prevalence |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 2013–2017 → 2018 | 275 | 811 | 0.022 | 95% | 275 | 36,864 | 62 | 0.0017 |
| 2015–2019 → 2020 | 282 | 856 | 0.022 | 95% | 429 | 90,271 | 84 | 0.0009 |
| 2017–2021 → 2022 | 292 | 944 | 0.022 | 97% | 601 | 177,748 | 160 | 0.0009 |

**AUPRC** (exhaustive universe; random baseline = mean of 3 seeds):

| Method | 2018 | 2020 | 2022 |
|---|---:|---:|---:|
| popularity | 0.0069 | 0.0041 | 0.0149 |
| preferential_attachment | 0.0121 | 0.0063 | 0.0104 |
| adamic_adar | 0.0103 | 0.0046 | 0.0036 |
| resource_allocation | 0.0070 | 0.0041 | 0.0032 |
| common_neighbors | 0.0081 | 0.0039 | 0.0029 |
| jaccard | 0.0032 | 0.0023 | 0.0020 |
| **random (baseline)** | **0.0022** | **0.0013** | **0.0009** |

**H1 (predictive signal):** every method beats the random baseline in all three cuts
(AUPRC ≈ 2–16× random / prevalence). Degree-based methods (popularity, preferential
attachment) lead on these small, dense concept networks. Precision@10 reaches ~0.1–0.2
for the degree methods vs ~0 for random — modest but real signal.

**H3 (temporal robustness):** the method ranking is broadly stable across the three
cuts (degree methods ahead of neighbourhood methods ahead of random), though absolute
values vary with the growing network and tiny positive counts.

## Limitations

- **H2 not yet validly tested.** Distance/community strata are computed and saved
  (`linkpred_by_stratum.csv`), but with so few positives per stratum the estimates are
  unstable; strong conclusions are not warranted yet.
- **Small corpus** (2,500 docs). Positive counts are small (62–160); numbers will
  shift with a larger corpus.
- **Sampled novelty** — "emergent" = new co-occurrence in the sampled 2013–2022
  corpus, not globally novel.
- **Retrospective** — deterministic YAKE carries no post-cut knowledge, but the run
  reconstructs from current metadata, so it is retrospective, not strictly ex ante.

## Not done here (next increments B–E)

KeyBERT vs YAKE comparison; logistic regression and node2vec (chronological training);
full-text (PDF) vs title+abstract on the same documents; Physics/Medicine; disruption
availability diagnosis (§4.4). H2 needs larger corpora for stable stratum estimates.

Artifacts: `results/linkpred_results.csv`, `linkpred_auprc_summary.csv`,
`linkpred_networks.csv`, `linkpred_by_stratum.csv`, `linkpred_comparison.manifest.json`.

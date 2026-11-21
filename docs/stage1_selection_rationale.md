# Stage 1 — selection rationale (eligibility, corpus type, domain recommendation)

This document records the *methodological* justifications behind the Stage-1
selection. All figures come from the measured artifacts in `results/` (aggregate
OpenAlex queries + reproducible samples); none depends on predictive performance.

## 1. Eligibility criteria and their justification

Eligibility is reported as **separate** verdicts, not one opaque flag, because the
downstream tasks have different data needs:

| Criterion | Level | Why this criterion | Default | Nature |
|---|---|---|---|---|
| `min_semantic_eligible_per_cut` | semantic | Enough English-abstract works per 5-year history window to build a concept vocabulary, co-occurrence network and candidate pairs. A link-prediction study needs tens of thousands of documents per cut. | 20,000 | essential (volume) |
| `min_english_abstract_fraction` | semantic | Guards against fields whose indexed output is mostly non-English or abstract-less, where the English-only corpus would be unrepresentative of the field. | 0.50 | representativeness |
| `min_with_references_fraction` | bibliometric | Reference coverage needed for the citation network and (later) disruption. Reported as a **bibliometric-readiness** flag; it does **not** remove a field from the *semantic* corpus. | 0.50 | bibliometric availability |

Subfield **count is NOT a gate** (it unfairly excluded coarse-taxonomy fields such
as Physics and Astronomy); it is reported descriptively together with normalized
subfield **entropy**.

**Why these numbers.** The thresholds are deliberately modest and defended on data
grounds, not tuned to admit particular disciplines. The sensitivity table
(`field_sensitivity.csv`) shows the eligible set is **insensitive** to the volume
and references gates at these levels (16 → 16 when either is removed) and is driven
almost entirely by the English-abstract threshold:

| English-abstract threshold | 0.30 | 0.40 | 0.50 (default) | 0.60 |
|---|---:|---:|---:|---:|
| # semantic-eligible fields | 25 | 23 | 16 | 5 |

We adopt **0.50** as the default because below it the English-only corpus covers a
minority of the field (so "Computer Science research" would really mean "the
English-abstract half of it"), while 0.60 is needlessly strict and would drop
fields with good absolute volume. This threshold is a **development decision**, to
be frozen before any predictive evaluation; the full curve is published so the
choice is auditable and can be revisited per research question.

**Semantic vs bibliometric separation.** The `no_references_gate` scenario is kept
precisely to show that reference coverage is treated as a *separate* axis: a field
that is semantically eligible but reference-sparse is still usable for the semantic
network, only flagged as not-yet bibliometric-ready. No field is called inadequate
for semantic networks merely for incomplete reference coverage.

## 2. Document-type (conference) decision

**Verified OpenAlex semantics.** A work carries exactly **one** `type`
(`group_by=type` buckets are disjoint and sum to the total). So `article` and
`conference-paper` are distinct, non-overlapping values — including conference
papers **adds disjoint works** (no double counting), which is why the corpus
sensitivity reflects genuine added volume.

**Decision (recorded before predictive evaluation).**
- **Primary corpus = `article`** (`config.corpus.types`), for a clean, comparable
  focal corpus across fields.
- **Alternative corpus = `article` + `conference-paper`** (`sensitivity_types`),
  reported via `--corpus-sensitivity`.

**Measured effect (2013–2022 semantic corpus):**

| Field | article-only | + conference | ratio |
|---|---:|---:|---:|
| Computer Science (17) | 1,105,805 | 2,116,838 | **1.91** |
| Physics and Astronomy (31) | 919,402 | 1,160,423 | 1.26 |
| Medicine (27) | 5,708,586 | 5,858,544 | 1.03 |

Conference papers nearly **double** the CS semantic corpus — a discipline-specific
effect (conferences are a primary CS venue). Because this materially changes the CS
corpus, the type choice for CS must be decided explicitly before building the
predictive corpus. The filter is **never changed silently** between fields or
periods: it is a single config value recorded in every manifest.

## 3. Weighted (interdisciplinary) characterization — Brito adaptation

`weighted_field_attribution.csv` compares primary-topic attribution with the
score-weighted distribution over each work's topics (adaptation of Brito, Silva &
Amancio 2023; OpenAlex topic scores used as relative weights only, not calibrated
probabilities). On 500 sampled works per candidate field:

| Field | % multidisciplinary (weight spans >1 field) | weighted self-share | main secondary fields |
|---|---:|---:|---|
| Computer Science (17) | ~48% | 0.95 | Social Sciences, Engineering, Mathematics |
| Physics and Astronomy (31) | ~52% | 0.95 | Engineering, Materials Science, Chemistry |
| Medicine (27) | ~40% | 0.96 | Biochemistry, Neuroscience, Health Professions |

All three candidates are strongly self-concentrated (primary ≈ weighted) yet carry
substantial secondary mass into *different* neighbours — evidence of complementary
interdisciplinary profiles, which supports choosing them together.

## 4. Textual quality (conditional, stratified)

`textual_quality_sampling.csv` and `textual_quality_by_year.csv` inspect **real**
sampled works. Results are **conditional on the English-abstract corpus filter**
(they are not whole-field coverage). On the candidates: 100% reconstructable
abstracts, 100% English, ~1–4% short, median 149–231 tokens. Stratified by year
(Computer Science), reference coverage **rises** 0.69 (2013) → 0.91 (2022) and
median abstract length grows — older records have sparser references, which matters
for the later citation/disruption work.

## 5. Domain recommendation (pre-selection, not final)

On the evidence above we **pre-select** three candidates for the main evaluation:

- **Medicine (27)** — Health Sciences; largest semantic corpus, 42 subfields,
  entropy 0.90; bibliometric-ready.
- **Physics and Astronomy (31)** — Physical Sciences; best documentary coverage
  (en 0.69, refs 0.90), high entropy; bibliometric-ready.
- **Computer Science (17)** — Physical Sciences; strong coverage and the most
  distinct interdisciplinary profile; bibliometric-ready.

They span 2 OpenAlex domains and 3 disciplines with complementary secondary-field
profiles. **Open items before the selection is FIXED:** (a) resolve the CS
document-type decision (conferences ≈ double the corpus); (b) freeze the selection
*before* seeing any predictive result. This is a development pre-selection, not the
final scientific choice.

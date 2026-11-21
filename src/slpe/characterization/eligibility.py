"""Field eligibility and sensitivity analysis for domain selection.

Eligibility is decided on DATA-QUALITY and FEASIBILITY grounds only, before any
predictive evaluation. Changes vs the audited version:

    * Subfield COUNT is no longer an eliminatory gate (it penalised fields with
      coarse OpenAlex taxonomies, e.g. Physics and Astronomy). It is reported as a
      descriptive attribute alongside normalized subfield entropy.
    * Eligibility is split into two transparent verdicts rather than one boolean:
        - ``semantic_eligible``:    enough English-abstract corpus-type works +
          adequate abstract coverage (basis for concept/network stages).
        - ``bibliometric_ready``:   additionally meets reference-coverage
          (needed for the citation network; does NOT prove disruption is measurable).
    * Each criterion carries its measured value next to the threshold.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from slpe.characterization.fields import FieldCharacterization
from slpe.config import Eligibility

if TYPE_CHECKING:
    import pandas as pd


@dataclass(frozen=True)
class Criterion:
    name: str
    passed: bool
    value: float
    threshold: float


@dataclass(frozen=True)
class EligibilityResult:
    field_id: int
    display_name: str
    domain: str
    semantic_eligible: bool
    bibliometric_ready: bool
    criteria: tuple[Criterion, ...]

    @property
    def failed_semantic(self) -> tuple[str, ...]:
        return tuple(
            f"{c.name} {c.value:.4g} < {c.threshold:.4g}"
            for c in self.criteria
            if c.name in _SEMANTIC_CRITERIA and not c.passed
        )


# Which criteria gate the semantic corpus (vs only the bibliometric readiness flag).
_SEMANTIC_CRITERIA = {"min_semantic_eligible_per_cut", "min_english_abstract_fraction"}


def evaluate_field(rec: FieldCharacterization, thr: Eligibility) -> EligibilityResult:
    criteria = (
        Criterion(
            "min_semantic_eligible_per_cut",
            rec.min_semantic_eligible_per_cut >= thr.min_semantic_eligible_per_cut,
            rec.min_semantic_eligible_per_cut, thr.min_semantic_eligible_per_cut,
        ),
        Criterion(
            "min_english_abstract_fraction",
            rec.english_abstract_fraction >= thr.min_english_abstract_fraction,
            rec.english_abstract_fraction, thr.min_english_abstract_fraction,
        ),
        Criterion(
            "min_with_references_fraction",
            rec.with_references_fraction >= thr.min_with_references_fraction,
            rec.with_references_fraction, thr.min_with_references_fraction,
        ),
    )
    semantic = all(c.passed for c in criteria if c.name in _SEMANTIC_CRITERIA)
    biblio = semantic and all(c.passed for c in criteria)
    return EligibilityResult(
        field_id=rec.field_id, display_name=rec.display_name, domain=rec.domain,
        semantic_eligible=semantic, bibliometric_ready=biblio, criteria=criteria,
    )


def evaluate_all(records: list[FieldCharacterization], thr: Eligibility) -> list[EligibilityResult]:
    return [evaluate_field(r, thr) for r in records]


def eligibility_to_dataframe(results: list[EligibilityResult]) -> pd.DataFrame:
    import pandas as pd

    rows = []
    for r in results:
        row = {
            "field_id": r.field_id,
            "display_name": r.display_name,
            "domain": r.domain,
            "semantic_eligible": r.semantic_eligible,
            "bibliometric_ready": r.bibliometric_ready,
            "failed_semantic_criteria": "; ".join(r.failed_semantic),
        }
        for c in r.criteria:
            row[f"{c.name}__value"] = c.value
            row[f"{c.name}__pass"] = c.passed
        rows.append(row)
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Sensitivity analysis
# ---------------------------------------------------------------------------

def sensitivity_analysis(
    records: list[FieldCharacterization], base: Eligibility
) -> pd.DataFrame:
    """Show how the eligible set changes as each criterion is varied or removed.

    Returns a tidy table: one row per scenario with the number and names of the
    semantically-eligible fields. Demonstrates that no single threshold silently
    dominates the selection.
    """
    from dataclasses import replace

    import pandas as pd

    scenarios: list[tuple[str, Eligibility]] = [("baseline", base)]
    # Remove each gate by relaxing it to a permissive value.
    scenarios.append(("no_volume_gate", replace(base, min_semantic_eligible_per_cut=0)))
    scenarios.append(("no_english_gate", replace(base, min_english_abstract_fraction=0.0)))
    scenarios.append(("no_references_gate", replace(base, min_with_references_fraction=0.0)))
    # Vary the English-abstract threshold.
    for frac in (0.3, 0.4, 0.5, 0.6):
        scenarios.append((f"english>={frac}", replace(base, min_english_abstract_fraction=frac)))

    rows = []
    for label, thr in scenarios:
        results = evaluate_all(records, thr)
        elig = [r for r in results if r.semantic_eligible]
        rows.append({
            "scenario": label,
            "n_semantic_eligible": len(elig),
            "fields": ", ".join(f"{r.display_name}({r.field_id})" for r in
                                 sorted(elig, key=lambda x: x.field_id)),
        })
    return pd.DataFrame(rows)


def legacy_eligibility_from_dataframe(
    df: pd.DataFrame,
    *,
    min_eligible_works_per_cut: int = 20000,
    min_english_abstract_fraction: float = 0.5,
    min_with_references_fraction: float = 0.5,
    min_subfield_diversity: int = 10,
    apply_subfield_gate: bool = True,
) -> pd.DataFrame:
    """Reproduce the AUDITED (legacy) eligibility from the original results CSV.

    Lets us confirm the audit's "6 eligible, 14 without the subfield gate" figures
    against the frozen original data, independent of the corrected pipeline. The
    legacy columns were: ``min_eligible_per_cut``, ``english_abstract_fraction``,
    ``with_references_fraction``, ``subfield_diversity``.
    """

    cols = {"min_eligible_per_cut", "english_abstract_fraction",
            "with_references_fraction", "subfield_diversity"}
    missing = cols - set(df.columns)
    if missing:
        raise KeyError(f"legacy CSV missing columns: {sorted(missing)}")

    def eligible(row: pd.Series) -> bool:
        ok = (
            row["min_eligible_per_cut"] >= min_eligible_works_per_cut
            and row["english_abstract_fraction"] >= min_english_abstract_fraction
            and row["with_references_fraction"] >= min_with_references_fraction
        )
        if apply_subfield_gate:
            ok = ok and row["subfield_diversity"] >= min_subfield_diversity
        return bool(ok)

    out = df.copy()
    out["legacy_eligible"] = out.apply(eligible, axis=1)
    return out

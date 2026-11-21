"""Field eligibility evaluation for domain selection.

Eligibility is decided on DATA-QUALITY and FEASIBILITY grounds only, before any
predictive evaluation — never on model accuracy on the final test data (a core
requirement of the project's selection protocol). Each field is checked against
configured thresholds; failures are reported transparently with the measured
value next to the threshold.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from slpe.config import Eligibility
from slpe.characterization.fields import FieldCharacterization

if TYPE_CHECKING:
    import pandas as pd


@dataclass(frozen=True)
class EligibilityResult:
    field_id: int
    display_name: str
    domain: str
    eligible: bool
    reasons: tuple[str, ...]  # failed-criterion messages (empty when eligible)


def evaluate_field(rec: FieldCharacterization, thr: Eligibility) -> EligibilityResult:
    reasons: list[str] = []
    if rec.min_eligible_per_cut < thr.min_eligible_works_per_cut:
        reasons.append(
            f"min eligible/cut {rec.min_eligible_per_cut} < {thr.min_eligible_works_per_cut}"
        )
    if rec.english_abstract_fraction < thr.min_english_abstract_fraction:
        reasons.append(
            f"en-abstract fraction {rec.english_abstract_fraction:.2f} "
            f"< {thr.min_english_abstract_fraction:.2f}"
        )
    if rec.with_references_fraction < thr.min_with_references_fraction:
        reasons.append(
            f"with-references fraction {rec.with_references_fraction:.2f} "
            f"< {thr.min_with_references_fraction:.2f}"
        )
    if rec.subfield_diversity < thr.min_subfield_diversity:
        reasons.append(
            f"subfield diversity {rec.subfield_diversity} < {thr.min_subfield_diversity}"
        )
    return EligibilityResult(
        field_id=rec.field_id,
        display_name=rec.display_name,
        domain=rec.domain,
        eligible=not reasons,
        reasons=tuple(reasons),
    )


def evaluate_all(
    records: list[FieldCharacterization], thr: Eligibility
) -> list[EligibilityResult]:
    return [evaluate_field(r, thr) for r in records]


def eligibility_to_dataframe(results: list[EligibilityResult]) -> "pd.DataFrame":
    import pandas as pd

    return pd.DataFrame(
        {
            "field_id": r.field_id,
            "display_name": r.display_name,
            "domain": r.domain,
            "eligible": r.eligible,
            "failed_criteria": "; ".join(r.reasons),
        }
        for r in results
    )

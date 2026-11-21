"""Stage 1 — characterization of the 26 OpenAlex fields and domain selection."""

from slpe.characterization.eligibility import (
    EligibilityResult,
    eligibility_to_dataframe,
    evaluate_all,
    evaluate_field,
    legacy_eligibility_from_dataframe,
    sensitivity_analysis,
)
from slpe.characterization.fields import (
    FieldCharacterization,
    FieldYearCounts,
    characterizations_to_dataframe,
    characterize_all_fields,
    characterize_field,
    normalized_entropy,
    years_to_dataframe,
)

__all__ = [
    "EligibilityResult",
    "FieldCharacterization",
    "FieldYearCounts",
    "characterizations_to_dataframe",
    "characterize_all_fields",
    "characterize_field",
    "eligibility_to_dataframe",
    "evaluate_all",
    "evaluate_field",
    "legacy_eligibility_from_dataframe",
    "normalized_entropy",
    "sensitivity_analysis",
    "years_to_dataframe",
]

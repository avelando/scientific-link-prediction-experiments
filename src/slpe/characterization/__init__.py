"""Stage 1 — characterization of the 26 OpenAlex fields and domain selection."""

from slpe.characterization.fields import (
    FieldCharacterization,
    FieldYearCounts,
    characterize_all_fields,
    characterize_field,
    characterizations_to_dataframe,
)

__all__ = [
    "FieldCharacterization",
    "FieldYearCounts",
    "characterize_all_fields",
    "characterize_field",
    "characterizations_to_dataframe",
]

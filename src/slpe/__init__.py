"""Scientific link-prediction experiments (preliminary phase).

Package layout:
    slpe.config            — typed config loading from YAML + environment.
    slpe.openalex          — OpenAlex HTTP client, caching, abstract reconstruction.
    slpe.characterization  — Stage 1: 26-field profiling and domain selection.

Later stages (corpus, concepts, networks, link prediction, disruption) attach as
sibling subpackages; see docs/traceability_matrix.md.
"""

__version__ = "0.1.0"

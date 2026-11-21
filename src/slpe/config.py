"""Typed configuration loaded from YAML + environment.

Design goals:
    * One source of truth for areas, temporal windows, hyperparameters, seeds, paths.
    * Secrets (API key) come ONLY from the environment, never from YAML/source.
    * Immutable dataclasses so config can't be mutated accidentally mid-run.

The temporal protocol validator enforces the project's leakage constraints
(eq. 3) so misconfigured cuts fail fast rather than silently leaking test data.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OpenAlexConfig:
    base_url: str
    mailto: str | None
    api_key: str | None
    per_page: int
    max_retries: int
    backoff_initial_seconds: float
    backoff_max_seconds: float
    timeout_seconds: float
    cache_dir: Path
    cache_enabled: bool
    min_interval_seconds: float


@dataclass(frozen=True)
class Paths:
    data_raw: Path
    data_interim: Path
    data_processed: Path
    results: Path
    logs: Path

    def ensure(self) -> None:
        for p in (self.data_raw, self.data_interim, self.data_processed, self.results, self.logs):
            p.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True)
class Eligibility:
    min_eligible_works_per_cut: int
    min_english_abstract_fraction: float
    min_with_references_fraction: float
    min_subfield_diversity: int


@dataclass(frozen=True)
class CharacterizationConfig:
    year_min: int
    year_max: int
    candidate_field_ids: tuple[int, ...]
    eligibility: Eligibility


@dataclass(frozen=True)
class TemporalCut:
    name: str
    history_start: int
    cut: int            # T
    emergence_year: int  # first year of (T, T+Delta_e]


@dataclass(frozen=True)
class TemporalConfig:
    history_window_years: int   # L
    emergence_horizon_years: int  # Delta_e
    disruption_horizon_years: int  # Delta_d
    cuts: tuple[TemporalCut, ...]


@dataclass(frozen=True)
class Config:
    seed: int
    openalex: OpenAlexConfig
    paths: Paths
    characterization: CharacterizationConfig
    temporal: TemporalConfig
    raw: dict[str, Any] = field(default_factory=dict, repr=False)


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

DEFAULT_CONFIG_PATH = Path("config/default.yaml")


def _resolve_path(base: Path, value: str) -> Path:
    p = Path(value)
    return p if p.is_absolute() else (base / p)


def load_config(
    path: str | Path = DEFAULT_CONFIG_PATH,
    *,
    project_root: Path | None = None,
    env: dict[str, str] | None = None,
) -> Config:
    """Load configuration from a YAML file, overlaying environment secrets.

    Args:
        path: YAML config path (absolute, or relative to ``project_root``).
        project_root: base for resolving relative paths; defaults to the current
            working directory. Relative data/cache paths resolve against it.
        env: environment mapping (defaults to ``os.environ``); injected for tests.

    Returns:
        A frozen :class:`Config`.
    """
    env = dict(os.environ if env is None else env)
    root = Path(project_root) if project_root is not None else Path.cwd()
    cfg_path = _resolve_path(root, str(path)) if not Path(path).is_absolute() else Path(path)

    with open(cfg_path, encoding="utf-8") as fh:
        data: dict[str, Any] = yaml.safe_load(fh) or {}

    oa = data.get("openalex", {})
    mailto = env.get("OPENALEX_MAILTO") or oa.get("mailto")
    api_key = env.get("OPENALEX_API_KEY") or None  # never read key from YAML

    openalex = OpenAlexConfig(
        base_url=str(oa.get("base_url", "https://api.openalex.org")).rstrip("/"),
        mailto=mailto,
        api_key=api_key,
        per_page=int(oa.get("per_page", 200)),
        max_retries=int(oa.get("max_retries", 5)),
        backoff_initial_seconds=float(oa.get("backoff_initial_seconds", 1.0)),
        backoff_max_seconds=float(oa.get("backoff_max_seconds", 60.0)),
        timeout_seconds=float(oa.get("timeout_seconds", 30.0)),
        cache_dir=_resolve_path(root, str(oa.get("cache_dir", "data/openalex_cache"))),
        cache_enabled=bool(oa.get("cache_enabled", True)),
        min_interval_seconds=float(oa.get("min_interval_seconds", 0.11)),
    )

    p = data.get("paths", {})
    paths = Paths(
        data_raw=_resolve_path(root, str(p.get("data_raw", "data/raw"))),
        data_interim=_resolve_path(root, str(p.get("data_interim", "data/interim"))),
        data_processed=_resolve_path(root, str(p.get("data_processed", "data/processed"))),
        results=_resolve_path(root, str(p.get("results", "results"))),
        logs=_resolve_path(root, str(p.get("logs", "logs"))),
    )

    ch = data.get("characterization", {})
    el = ch.get("eligibility", {})
    characterization = CharacterizationConfig(
        year_min=int(ch.get("year_min", 2013)),
        year_max=int(ch.get("year_max", 2022)),
        candidate_field_ids=tuple(int(x) for x in ch.get("candidate_field_ids", [])),
        eligibility=Eligibility(
            min_eligible_works_per_cut=int(el.get("min_eligible_works_per_cut", 20000)),
            min_english_abstract_fraction=float(el.get("min_english_abstract_fraction", 0.5)),
            min_with_references_fraction=float(el.get("min_with_references_fraction", 0.5)),
            min_subfield_diversity=int(el.get("min_subfield_diversity", 10)),
        ),
    )

    t = data.get("temporal", {})
    cuts = tuple(
        TemporalCut(
            name=str(c["name"]),
            history_start=int(c["history_start"]),
            cut=int(c["cut"]),
            emergence_year=int(c["emergence_year"]),
        )
        for c in t.get("cuts", [])
    )
    temporal = TemporalConfig(
        history_window_years=int(t.get("history_window_years", 5)),
        emergence_horizon_years=int(t.get("emergence_horizon_years", 1)),
        disruption_horizon_years=int(t.get("disruption_horizon_years", 3)),
        cuts=cuts,
    )

    return Config(
        seed=int(data.get("seed", 0)),
        openalex=openalex,
        paths=paths,
        characterization=characterization,
        temporal=temporal,
        raw=data,
    )


def validate_temporal_protocol(temporal: TemporalConfig) -> list[str]:
    """Check the project's leakage constraints for train/val/test triples (eq. 3).

    Interprets consecutive configured cuts as (train, val, test) and verifies
    ``T_tr + Δe + Δd <= T_val`` and ``T_val + Δe + Δd <= T_te``. Returns a list of
    human-readable violations (empty when the configuration is sound).

    This is advisory for the *preliminary* retrospective cuts (which are repeated
    evaluations, not independent splits); it becomes binding when cuts are used as
    a train/val/test triple for the disruption-regression stage.
    """
    violations: list[str] = []
    de, dd = temporal.emergence_horizon_years, temporal.disruption_horizon_years
    cuts = temporal.cuts
    if len(cuts) >= 3:
        tr, val, te = cuts[0].cut, cuts[1].cut, cuts[2].cut
        if tr + de + dd > val:
            violations.append(
                f"T_tr({tr})+Δe({de})+Δd({dd})={tr + de + dd} > T_val({val})"
            )
        if val + de + dd > te:
            violations.append(
                f"T_val({val})+Δe({de})+Δd({dd})={val + de + dd} > T_te({te})"
            )
    for c in cuts:
        if c.cut - c.history_start + 1 <= 0:
            violations.append(f"cut {c.name}: non-positive history window")
        if c.emergence_year <= c.cut:
            violations.append(f"cut {c.name}: emergence_year must be > cut")
    return violations

"""Tests for config loading, secret handling and the temporal-protocol validator."""

from pathlib import Path

import pytest

from slpe.config import (
    TemporalConfig,
    TemporalCut,
    load_config,
    validate_temporal_protocol,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_load_default_config_resolves_paths_and_cuts():
    cfg = load_config(REPO_ROOT / "config" / "default.yaml", project_root=REPO_ROOT, env={})
    assert cfg.characterization.year_min == 2013
    assert cfg.characterization.year_max == 2022
    assert len(cfg.temporal.cuts) == 3
    assert cfg.temporal.cuts[0].cut == 2017
    assert cfg.openalex.cache_dir.is_absolute()


def test_api_key_comes_only_from_env_not_yaml():
    cfg = load_config(
        REPO_ROOT / "config" / "default.yaml",
        project_root=REPO_ROOT,
        env={"OPENALEX_API_KEY": "secret123", "OPENALEX_MAILTO": "a@b.org"},
    )
    assert cfg.openalex.api_key == "secret123"
    assert cfg.openalex.mailto == "a@b.org"
    # The YAML has no api_key field, so with empty env it must be None.
    cfg2 = load_config(REPO_ROOT / "config" / "default.yaml", project_root=REPO_ROOT, env={})
    assert cfg2.openalex.api_key is None


def test_temporal_protocol_valid_triple_passes():
    # Spaced so that T_tr+Δe+Δd <= T_val and T_val+Δe+Δd <= T_te.
    t = TemporalConfig(
        history_window_years=5,
        emergence_horizon_years=1,
        disruption_horizon_years=3,
        cuts=(
            TemporalCut("tr", 2004, 2008, 2009),
            TemporalCut("val", 2008, 2012, 2013),
            TemporalCut("te", 2012, 2016, 2017),
        ),
    )
    assert validate_temporal_protocol(t) == []


def test_temporal_protocol_detects_leakage():
    # The preliminary cuts (2017/2019/2021, Δe=1, Δd=3) overlap -> advisory flags.
    t = TemporalConfig(
        history_window_years=5,
        emergence_horizon_years=1,
        disruption_horizon_years=3,
        cuts=(
            TemporalCut("a", 2013, 2017, 2018),
            TemporalCut("b", 2015, 2019, 2020),
            TemporalCut("c", 2017, 2021, 2022),
        ),
    )
    violations = validate_temporal_protocol(t)
    assert violations  # 2017+1+3=2021 > 2019 => leakage for a full disruption split
    assert any("T_tr" in v for v in violations)


def test_temporal_protocol_flags_bad_cut():
    t = TemporalConfig(5, 1, 3, cuts=(TemporalCut("x", 2015, 2010, 2009),))
    violations = validate_temporal_protocol(t)
    assert any("emergence_year" in v for v in violations)

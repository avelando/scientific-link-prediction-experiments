"""Tests for config loading, secrets, dotenv, validation and temporal protocol."""

from pathlib import Path

from slpe.config import (
    TemporalConfig,
    TemporalCut,
    load_config,
    load_dotenv_if_present,
    validate_config,
    validate_temporal_protocol,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_load_default_config():
    cfg = load_config(REPO_ROOT / "config" / "default.yaml", project_root=REPO_ROOT, env={})
    assert cfg.characterization.year_min == 2013
    assert len(cfg.temporal.cuts) == 3
    assert cfg.corpus.types == ("article",)
    assert cfg.corpus.sensitivity_types[:2] == ("article", "conference-paper")
    assert cfg.openalex.cache_dir.is_absolute()


def test_api_key_only_from_env():
    cfg = load_config(REPO_ROOT / "config" / "default.yaml", project_root=REPO_ROOT,
                      env={"OPENALEX_API_KEY": "secret123", "OPENALEX_MAILTO": "a@b.org"})
    assert cfg.openalex.api_key == "secret123"
    cfg2 = load_config(REPO_ROOT / "config" / "default.yaml", project_root=REPO_ROOT, env={})
    assert cfg2.openalex.api_key is None


def test_dotenv_loaded_without_override(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("OPENALEX_MAILTO=fromdotenv@x.org\n", encoding="utf-8")
    monkeypatch.delenv("OPENALEX_MAILTO", raising=False)
    loaded = load_dotenv_if_present(tmp_path / ".env")
    assert "OPENALEX_MAILTO" in loaded
    import os
    assert os.environ["OPENALEX_MAILTO"] == "fromdotenv@x.org"
    monkeypatch.delenv("OPENALEX_MAILTO", raising=False)


def test_validate_config_rejects_bad_ranges():
    cfg = load_config(REPO_ROOT / "config" / "default.yaml", project_root=REPO_ROOT, env={})
    # Frozen dataclass; build a broken copy via dataclasses.replace on nested.
    from dataclasses import replace
    bad = replace(cfg, openalex=replace(cfg.openalex, per_page=9999))
    problems = validate_config(bad)
    assert any("per_page" in p for p in problems)


def test_temporal_protocol_valid_triple_passes():
    t = TemporalConfig(5, 1, 3, cuts=(
        TemporalCut("tr", 2004, 2008, 2009),
        TemporalCut("val", 2008, 2012, 2013),
        TemporalCut("te", 2012, 2016, 2017),
    ))
    assert validate_temporal_protocol(t) == []


def test_temporal_protocol_detects_leakage():
    t = TemporalConfig(5, 1, 3, cuts=(
        TemporalCut("a", 2013, 2017, 2018),
        TemporalCut("b", 2015, 2019, 2020),
        TemporalCut("c", 2017, 2021, 2022),
    ))
    violations = validate_temporal_protocol(t)
    assert any("T_tr" in v for v in violations)


def test_temporal_protocol_flags_L_mismatch():
    # history window 2013..2017 = 5, but L declared as 7 -> mismatch.
    t = TemporalConfig(7, 1, 3, cuts=(TemporalCut("x", 2013, 2017, 2018),))
    violations = validate_temporal_protocol(t)
    assert any("history window" in v for v in violations)


def test_temporal_protocol_flags_emergence_year():
    t = TemporalConfig(5, 1, 3, cuts=(TemporalCut("x", 2013, 2017, 2020),))
    violations = validate_temporal_protocol(t)
    assert any("emergence_year" in v for v in violations)

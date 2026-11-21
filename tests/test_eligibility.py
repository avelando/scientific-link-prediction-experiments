"""Tests for the revised eligibility, sensitivity analysis and legacy reproduction."""

import pandas as pd

from slpe.characterization.eligibility import (
    evaluate_field,
    legacy_eligibility_from_dataframe,
    sensitivity_analysis,
)
from slpe.characterization.fields import FieldCharacterization, FieldYearCounts
from slpe.config import Eligibility


def _rec(fid, semantic_min, en_frac, ref_frac, subfields=8):
    years = [FieldYearCounts(y, 100, 50, 40, 30) for y in range(2013, 2023)]
    return FieldCharacterization(
        field_id=fid, display_name=f"F{fid}", domain="D", works_count_all_time=1,
        corpus_types=("article",), years=years,
        subfield_count=subfields, subfield_entropy=0.5,
        all_types_in_range=1000, corpus_type_in_range=500,
        semantic_in_range=400, bibliometric_in_range=300,
        type_fraction=0.5, english_abstract_fraction=en_frac, with_references_fraction=ref_frac,
        semantic_eligible_per_cut={"c1": semantic_min}, bibliometric_eligible_per_cut={"c1": 999999},
    )


def test_subfield_count_is_not_a_gate():
    thr = Eligibility(20000, 0.5, 0.5)
    # Only 2 subfields but strong coverage/volume -> still semantic-eligible.
    rec = _rec(31, semantic_min=600000, en_frac=0.62, ref_frac=0.82, subfields=2)
    res = evaluate_field(rec, thr)
    assert res.semantic_eligible is True
    assert res.bibliometric_ready is True


def test_semantic_vs_bibliometric_split():
    thr = Eligibility(20000, 0.5, 0.5)
    # Enough text coverage but low references -> semantic-eligible, not biblio-ready.
    rec = _rec(1, semantic_min=50000, en_frac=0.6, ref_frac=0.3)
    res = evaluate_field(rec, thr)
    assert res.semantic_eligible is True
    assert res.bibliometric_ready is False


def test_low_volume_fails_semantic():
    thr = Eligibility(20000, 0.5, 0.5)
    rec = _rec(2, semantic_min=100, en_frac=0.6, ref_frac=0.6)
    res = evaluate_field(rec, thr)
    assert res.semantic_eligible is False


def test_sensitivity_analysis_varies_counts():
    thr = Eligibility(20000, 0.5, 0.5)
    recs = [
        _rec(1, 50000, 0.60, 0.60),   # eligible
        _rec(2, 50000, 0.45, 0.60),   # fails english at baseline
        _rec(3, 100, 0.60, 0.60),     # fails volume
    ]
    sens = sensitivity_analysis(recs, thr)
    base = sens[sens["scenario"] == "baseline"]["n_semantic_eligible"].iloc[0]
    no_vol = sens[sens["scenario"] == "no_volume_gate"]["n_semantic_eligible"].iloc[0]
    no_en = sens[sens["scenario"] == "no_english_gate"]["n_semantic_eligible"].iloc[0]
    assert base == 1
    assert no_vol == 2       # field 3 now passes
    assert no_en == 2        # field 2 now passes


def test_legacy_reproduction_subfield_gate_effect():
    # Minimal legacy-shaped frame: gate removes some fields.
    df = pd.DataFrame([
        {"min_eligible_per_cut": 500000, "english_abstract_fraction": 0.6,
         "with_references_fraction": 0.8, "subfield_diversity": 8},   # fails gate only
        {"min_eligible_per_cut": 500000, "english_abstract_fraction": 0.6,
         "with_references_fraction": 0.8, "subfield_diversity": 12},  # passes both
    ])
    with_gate = legacy_eligibility_from_dataframe(df, apply_subfield_gate=True)
    without_gate = legacy_eligibility_from_dataframe(df, apply_subfield_gate=False)
    assert int(with_gate["legacy_eligible"].sum()) == 1
    assert int(without_gate["legacy_eligible"].sum()) == 2

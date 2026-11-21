"""Tests for field characterization math and eligibility, with a stub client."""

from slpe.characterization.eligibility import evaluate_field
from slpe.characterization.fields import _field_numeric_id, characterize_field
from slpe.config import CharacterizationConfig, Eligibility, TemporalConfig, TemporalCut


class StubClient:
    """Returns canned group_by buckets keyed by the group_by dimension+filter."""

    def __init__(self, year_totals, year_en, year_eligible, subfield_keys):
        self.year_totals = year_totals
        self.year_en = year_en
        self.year_eligible = year_eligible
        self.subfield_keys = subfield_keys

    def group_by(self, path, group_by, filters=None, **extra):
        if group_by == "primary_topic.subfield.id":
            return [{"key": k, "count": 10} for k in self.subfield_keys]
        if group_by == "publication_year":
            if "has_references:true" in (filters or ""):
                src = self.year_eligible
            elif "language:en" in (filters or ""):
                src = self.year_en
            else:
                src = self.year_totals
            return [{"key": str(y), "count": n} for y, n in src.items()]
        raise AssertionError(f"unexpected group_by {group_by}")


def _cfg():
    ch = CharacterizationConfig(
        year_min=2013,
        year_max=2022,
        candidate_field_ids=(17,),
        eligibility=Eligibility(
            min_eligible_works_per_cut=100,
            min_english_abstract_fraction=0.5,
            min_with_references_fraction=0.5,
            min_subfield_diversity=3,
        ),
    )
    temporal = TemporalConfig(
        history_window_years=5,
        emergence_horizon_years=1,
        disruption_horizon_years=3,
        cuts=(
            TemporalCut("2017_to_2018", 2013, 2017, 2018),
            TemporalCut("2019_to_2020", 2015, 2019, 2020),
            TemporalCut("2021_to_2022", 2017, 2021, 2022),
        ),
    )
    return ch, temporal


def test_field_numeric_id_parsing():
    assert _field_numeric_id("https://openalex.org/fields/17") == 17
    assert _field_numeric_id("fields/27") == 27
    assert _field_numeric_id("31") == 31


def test_characterize_field_fractions_and_per_cut():
    ch, temporal = _cfg()
    years = range(2013, 2023)
    totals = {y: 1000 for y in years}
    en = {y: 800 for y in years}           # 80% english-abstract
    eligible = {y: 600 for y in years}     # 600/800 = 75% with references
    stub = StubClient(totals, en, eligible, subfield_keys=["a", "b", "c", "d"])

    field_obj = {
        "id": "https://openalex.org/fields/17",
        "display_name": "Computer Science",
        "works_count": 9_000_000,
        "domain": {"display_name": "Physical Sciences"},
    }
    rec = characterize_field(stub, field_obj, ch, temporal)

    assert rec.field_id == 17
    assert rec.total_in_range == 10_000
    assert abs(rec.english_abstract_fraction - 0.8) < 1e-9
    assert abs(rec.with_references_fraction - 0.75) < 1e-9
    assert rec.subfield_diversity == 4
    # history window 2013..2017 = 5 years * 600 eligible = 3000
    assert rec.eligible_per_cut["2017_to_2018"] == 3000
    assert rec.min_eligible_per_cut == 3000


def test_eligibility_pass_and_fail():
    ch, temporal = _cfg()
    years = range(2013, 2023)
    stub_ok = StubClient(
        {y: 1000 for y in years}, {y: 800 for y in years}, {y: 600 for y in years},
        subfield_keys=["a", "b", "c", "d"],
    )
    field_obj = {"id": "fields/17", "display_name": "CS", "works_count": 1,
                 "domain": {"display_name": "D"}}
    rec = characterize_field(stub_ok, field_obj, ch, temporal)
    assert evaluate_field(rec, ch.eligibility).eligible

    # Low english fraction + too few subfields -> ineligible with reasons.
    stub_bad = StubClient(
        {y: 1000 for y in years}, {y: 200 for y in years}, {y: 150 for y in years},
        subfield_keys=["a"],
    )
    rec_bad = characterize_field(stub_bad, field_obj, ch, temporal)
    res = evaluate_field(rec_bad, ch.eligibility)
    assert not res.eligible
    assert any("en-abstract fraction" in r for r in res.reasons)
    assert any("subfield diversity" in r for r in res.reasons)

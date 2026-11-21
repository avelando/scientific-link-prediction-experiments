"""Tests for field characterization (three coverage levels) and entropy."""

from slpe.characterization.fields import (
    _field_numeric_id,
    characterize_field,
    normalized_entropy,
)
from slpe.config import (
    CharacterizationConfig,
    CorpusConfig,
    Eligibility,
    TemporalConfig,
    TemporalCut,
)


class StubClient:
    """Returns canned year buckets per coverage level, inferred from the filter."""

    def __init__(self, all_types, corpus_type, semantic, bibliometric, subfield_counts):
        self.all_types = all_types
        self.corpus_type = corpus_type
        self.semantic = semantic
        self.bibliometric = bibliometric
        self.subfield_counts = subfield_counts
        self.seen_type_filter = False

    def group_by(self, path, group_by, filters=None, **extra):
        f = filters or ""
        if "type:" in f:
            self.seen_type_filter = True
        if group_by == "primary_topic.subfield.id":
            return [{"key": f"s{i}", "count": c} for i, c in enumerate(self.subfield_counts)]
        if group_by == "publication_year":
            if "has_references:true" in f:
                src = self.bibliometric
            elif "language:en" in f:
                src = self.semantic
            elif "type:" in f:
                src = self.corpus_type
            else:
                src = self.all_types
            return [{"key": str(y), "count": n} for y, n in src.items()]
        raise AssertionError(f"unexpected group_by {group_by}")


def _cfg():
    ch = CharacterizationConfig(
        year_min=2013, year_max=2022, candidate_field_ids=(17,),
        eligibility=Eligibility(20000, 0.5, 0.5),
    )
    temporal = TemporalConfig(5, 1, 3, cuts=(
        TemporalCut("2017_to_2018", 2013, 2017, 2018),
        TemporalCut("2019_to_2020", 2015, 2019, 2020),
        TemporalCut("2021_to_2022", 2017, 2021, 2022),
    ))
    corpus = CorpusConfig(types=("article",), sensitivity_types=("article", "conference-paper"),
                          require_english_abstract=True)
    return ch, temporal, corpus


def test_field_numeric_id_parsing():
    assert _field_numeric_id("https://openalex.org/fields/17") == 17
    assert _field_numeric_id("fields/27") == 27
    assert _field_numeric_id("31") == 31


def test_normalized_entropy_bounds():
    assert normalized_entropy([]) == 0.0
    assert normalized_entropy([10]) == 0.0
    assert abs(normalized_entropy([5, 5]) - 1.0) < 1e-9       # even split -> max
    assert 0.0 < normalized_entropy([90, 5, 5]) < 1.0         # concentrated -> low


def test_three_levels_and_fractions():
    ch, temporal, corpus = _cfg()
    years = range(2013, 2023)
    all_types = {y: 2000 for y in years}
    corpus_type = {y: 1000 for y in years}   # type:article captures half
    semantic = {y: 800 for y in years}       # 800/1000 english-abstract
    bibliometric = {y: 600 for y in years}   # 600/800 with references
    stub = StubClient(all_types, corpus_type, semantic, bibliometric,
                      subfield_counts=[400, 300, 200, 100])

    field_obj = {"id": "fields/17", "display_name": "Computer Science",
                 "works_count": 9_000_000, "domain": {"display_name": "Physical Sciences"}}
    rec = characterize_field(stub, field_obj, ch, temporal, corpus)

    assert stub.seen_type_filter  # the type filter was actually applied
    assert rec.all_types_in_range == 20000
    assert rec.corpus_type_in_range == 10000
    assert abs(rec.type_fraction - 0.5) < 1e-9
    assert abs(rec.english_abstract_fraction - 0.8) < 1e-9
    assert abs(rec.with_references_fraction - 0.75) < 1e-9
    assert rec.subfield_count == 4
    assert 0.0 < rec.subfield_entropy < 1.0
    # semantic history window 2013..2017 = 5 * 800 = 4000
    assert rec.semantic_eligible_per_cut["2017_to_2018"] == 4000
    assert rec.bibliometric_eligible_per_cut["2017_to_2018"] == 3000

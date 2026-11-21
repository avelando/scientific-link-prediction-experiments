"""Tests for the OpenAlex adaptation of Brito-style weighted field attribution."""

from slpe.characterization.weighting import (
    aggregate_field_distribution,
    primary_field,
    work_field_weights,
)


def _topic(field_id, score):
    return {"field": {"id": f"https://openalex.org/fields/{field_id}"}, "score": score}


def test_single_topic_whole_weight():
    work = {"primary_topic": _topic(17, 0.9), "topics": [_topic(17, 0.9)]}
    assert primary_field(work) == 17
    assert work_field_weights(work) == {17: 1.0}


def test_multiple_topics_same_field_sum_to_one():
    work = {"primary_topic": _topic(17, 0.6),
            "topics": [_topic(17, 0.6), _topic(17, 0.3)]}
    w = work_field_weights(work)
    assert set(w) == {17}
    assert abs(w[17] - 1.0) < 1e-9


def test_topics_different_fields_split_by_score():
    work = {"primary_topic": _topic(17, 0.6),
            "topics": [_topic(17, 0.6), _topic(31, 0.2)]}
    w = work_field_weights(work)
    assert abs(w[17] - 0.75) < 1e-9
    assert abs(w[31] - 0.25) < 1e-9


def test_missing_scores_fall_back_to_equal_split():
    work = {"primary_topic": _topic(17, None),
            "topics": [{"field": {"id": "fields/17"}}, {"field": {"id": "fields/31"}}]}
    w = work_field_weights(work)
    assert abs(w[17] - 0.5) < 1e-9 and abs(w[31] - 0.5) < 1e-9


def test_invalid_metadata_contributes_nowhere():
    assert work_field_weights({"topics": []}) == {}
    assert work_field_weights({"topics": [{"not_a_field": 1}]}) == {}
    assert primary_field({"primary_topic": None}) is None


def test_aggregate_counts_multidisciplinary():
    works = [
        {"primary_topic": _topic(17, 0.9), "topics": [_topic(17, 0.9)]},
        {"primary_topic": _topic(17, 0.6), "topics": [_topic(17, 0.6), _topic(31, 0.4)]},
    ]
    attr = aggregate_field_distribution(works)
    assert attr.n_works == 2
    assert attr.n_multidisciplinary == 1
    assert attr.primary_counts[17] == 2.0
    # weighted: work1 -> 17:1.0 ; work2 -> 17:0.6, 31:0.4
    assert abs(attr.weighted_counts[17] - 1.6) < 1e-9
    assert abs(attr.weighted_counts[31] - 0.4) < 1e-9

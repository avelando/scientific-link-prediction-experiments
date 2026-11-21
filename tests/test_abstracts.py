"""Tests for abstract reconstruction from OpenAlex inverted indices."""

from slpe.openalex.abstracts import reconstruct_abstract


def test_basic_reconstruction():
    idx = {"The": [0], "quick": [1], "brown": [2], "fox": [3]}
    assert reconstruct_abstract(idx) == "The quick brown fox"


def test_repeated_tokens_at_multiple_positions():
    idx = {"the": [0, 2], "cat": [1], "hat": [3]}
    assert reconstruct_abstract(idx) == "the cat the hat"


def test_none_and_empty_return_none():
    assert reconstruct_abstract(None) is None
    assert reconstruct_abstract({}) is None


def test_gaps_in_positions_are_skipped_not_padded():
    # Missing position 1: we join present tokens in order, no blank filler.
    idx = {"alpha": [0], "gamma": [2]}
    assert reconstruct_abstract(idx) == "alpha gamma"


def test_negative_and_noninteger_positions_ignored():
    idx = {"good": [0], "bad": [-1], "ugly": ["x"]}  # type: ignore[list-item]
    assert reconstruct_abstract(idx) == "good"


def test_max_tokens_truncates_by_position_order():
    idx = {"a": [0], "b": [1], "c": [2], "d": [3]}
    assert reconstruct_abstract(idx, max_tokens=2) == "a b"


def test_out_of_order_index_is_sorted_by_position():
    idx = {"world": [1], "hello": [0]}
    assert reconstruct_abstract(idx) == "hello world"

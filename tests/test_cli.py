"""Test that --limit restricts fields BEFORE queries are issued."""

from slpe.characterization.fields import characterize_all_fields
from slpe.config import (
    CharacterizationConfig,
    CorpusConfig,
    Eligibility,
    TemporalConfig,
    TemporalCut,
)


class CountingClient:
    def __init__(self, n_fields):
        self.n_fields = n_fields
        self.fields_queried = set()

    def list_all(self, path, **extra):
        return [{"id": f"fields/{i}", "display_name": f"F{i}", "works_count": 1,
                 "domain": {"display_name": "D"}} for i in range(self.n_fields)]

    def group_by(self, path, group_by, filters=None, **extra):
        # Record which field is being queried (parse from the filter).
        import re
        m = re.search(r"primary_topic\.field\.id:(\d+)", filters or "")
        if m:
            self.fields_queried.add(int(m.group(1)))
        if group_by == "primary_topic.subfield.id":
            return [{"key": "s0", "count": 10}]
        return [{"key": "2015", "count": 100}]


def _cfg():
    ch = CharacterizationConfig(2013, 2022, (17,), Eligibility(1, 0.0, 0.0))
    temporal = TemporalConfig(5, 1, 3, cuts=(TemporalCut("c", 2013, 2017, 2018),))
    corpus = CorpusConfig(("article",), ("article", "conference-paper"), True)
    return ch, temporal, corpus


def test_limit_restricts_fields_before_queries():
    ch, temporal, corpus = _cfg()
    client = CountingClient(n_fields=5)
    records = characterize_all_fields(client, ch, temporal, corpus, limit=2, progress=False)
    assert len(records) == 2
    # Only the first two fields (ids 0 and 1) were ever queried.
    assert client.fields_queried == {0, 1}

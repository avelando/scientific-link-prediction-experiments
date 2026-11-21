"""Incremental, resumable historical collector for OpenAlex works.

Collects works for a field over a year range and writes three relational datasets
(publications / topics / references) to the raw layer, in page-sized batches.

Resumability is transactional: each page is normalized and written (atomic part
files named by page index) BEFORE the pagination cursor advances, via
:meth:`OpenAlexClient.fetch_pages`. A crash re-fetches the in-flight page and
rewrites the same deterministically-named part files (idempotent). Cursor paging
does not return duplicates; cross-run/cross-cut duplicates are handled by dedup.

``max_records`` gives a test/pilot mode. Nothing starts a full multi-million-row
download implicitly — the caller must choose the mode.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from slpe.collection import WORKS_SELECT
from slpe.collection.io_parquet import dataset_dir, write_batch
from slpe.collection.schema import (
    PUBLICATIONS_SCHEMA,
    REFERENCES_SCHEMA,
    TOPICS_SCHEMA,
    normalize_work,
)
from slpe.openalex.client import OpenAlexClient

logger = logging.getLogger("slpe.collection")


@dataclass
class CollectionResult:
    field_id: int
    dataset: str
    n_works: int
    n_pages: int = 0
    pub_dir: Path | None = None
    topics_dir: Path | None = None
    refs_dir: Path | None = None


@dataclass
class HistoricalCollector:
    client: OpenAlexClient
    base_dir: Path
    layer: str = "raw"
    _pages: int = field(default=0, repr=False)

    def collect_field(
        self,
        field_id: int,
        *,
        year_min: int,
        year_max: int,
        corpus_filter: str,
        dataset_name: str,
        checkpoint_path: str | Path,
        max_records: int | None = None,
        per_page: int = 200,
    ) -> CollectionResult:
        """Collect a field's works for a year range into raw parquet datasets."""
        base = Path(self.base_dir)
        pub_dir = dataset_dir(base, self.layer, f"{dataset_name}/publications")
        topics_dir = dataset_dir(base, self.layer, f"{dataset_name}/topics")
        refs_dir = dataset_dir(base, self.layer, f"{dataset_name}/references")

        filters = (
            f"primary_topic.field.id:{field_id},"
            f"from_publication_date:{year_min}-01-01,"
            f"to_publication_date:{year_max}-12-31"
        )
        if corpus_filter:
            filters = f"{filters},{corpus_filter}"

        self._pages = 0

        def on_page(rows: list[dict[str, Any]], page_index: int) -> None:
            pubs, topics, refs = [], [], []
            for work in rows:
                nw = normalize_work(work)
                pubs.append(nw.publication)
                topics.extend(nw.topics)
                refs.extend(nw.references)
            # Write all three tables for this page; part files are named by page
            # index so a re-delivered page overwrites rather than duplicates.
            write_batch(pubs, PUBLICATIONS_SCHEMA, pub_dir, page_index)
            write_batch(topics, TOPICS_SCHEMA, topics_dir, page_index)
            write_batch(refs, REFERENCES_SCHEMA, refs_dir, page_index)
            self._pages = max(self._pages, page_index + 1)
            logger.info("field %d page %d: +%d works", field_id, page_index, len(rows))

        total = self.client.fetch_pages(
            "works", on_page, filters=filters, select=WORKS_SELECT,
            per_page=per_page, checkpoint_path=checkpoint_path, max_records=max_records,
        )
        return CollectionResult(
            field_id=field_id, dataset=dataset_name, n_works=total, n_pages=self._pages,
            pub_dir=pub_dir, topics_dir=topics_dir, refs_dir=refs_dir,
        )

"""Parquet I/O for the raw/interim/processed layers.

A "dataset" is a directory of part files (``part-00000.parquet`` ...). Batches are
appended as new part files, so collection never holds the whole corpus in memory.
Reading uses ``pyarrow.dataset`` for columnar, predicate-pushdown scans.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.dataset as ds
import pyarrow.parquet as pq


def dataset_dir(base: Path, layer: str, name: str) -> Path:
    """Path for a dataset in a layer, e.g. base/raw/publications."""
    d = Path(base) / layer / name
    d.mkdir(parents=True, exist_ok=True)
    return d


def write_batch(
    records: list[dict[str, Any]],
    schema: pa.Schema,
    out_dir: Path,
    batch_index: int,
) -> Path:
    """Append a batch of records as one part file. Empty batches write nothing."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"part-{batch_index:05d}.parquet"
    if not records:
        return path
    # Coerce each column explicitly per the schema (handles missing keys as null).
    columns = {field.name: [r.get(field.name) for r in records] for field in schema}
    table = pa.table(columns, schema=schema)
    tmp = path.with_suffix(".parquet.tmp")
    pq.write_table(table, tmp)
    tmp.replace(path)  # atomic publish of the part file
    return path


def read_dataset(out_dir: Path, columns: list[str] | None = None) -> pa.Table:
    """Read an entire dataset (all part files) into a single Arrow table."""
    out_dir = Path(out_dir)
    parts = sorted(out_dir.glob("part-*.parquet"))
    if not parts:
        return pa.table({})
    dataset = ds.dataset([str(p) for p in parts], format="parquet")
    return dataset.to_table(columns=columns)


def iter_batches(out_dir: Path, columns: list[str] | None = None,
                 batch_size: int = 50_000) -> Iterable[pa.RecordBatch]:
    """Stream a dataset in record batches (bounded memory)."""
    parts = sorted(Path(out_dir).glob("part-*.parquet"))
    if not parts:
        return
    dataset = ds.dataset([str(p) for p in parts], format="parquet")
    yield from dataset.to_batches(columns=columns, batch_size=batch_size)


def dataset_count(out_dir: Path) -> int:
    parts = sorted(Path(out_dir).glob("part-*.parquet"))
    return sum(pq.read_metadata(p).num_rows for p in parts)


# --- integrity checks ------------------------------------------------------

def check_publications_integrity(table: pa.Table) -> list[str]:
    """Validate the publications table. Returns a list of problems (empty = OK)."""
    problems: list[str] = []
    if table.num_rows == 0:
        return ["publications table is empty"]


    df = table.to_pandas()
    # Unique work ids.
    n_dupe = int(df["work_id"].duplicated().sum())
    if n_dupe:
        problems.append(f"{n_dupe} duplicate work_id rows")
    # Required fields present.
    n_missing_id = int(df["work_id"].isna().sum())
    if n_missing_id:
        problems.append(f"{n_missing_id} rows with null work_id")
    # Date/year consistency where both present.
    both = df.dropna(subset=["publication_year", "publication_date"])
    if len(both):
        date_year = both["publication_date"].astype(str).str[:4]
        row_year = both["publication_year"].astype("Int64").astype(str)
        mismatched = both[date_year.values != row_year.values]
        if len(mismatched):
            problems.append(f"{len(mismatched)} rows with year/date mismatch")
    return problems

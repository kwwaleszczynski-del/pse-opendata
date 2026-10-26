"""Monthly Parquet cache files."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from pse_opendata.cache import MonthCache
from pse_opendata.catalog import get_report
from pse_opendata.frames import parse_records

from conftest import api_records


def frame() -> pd.DataFrame:
    return parse_records(api_records("rce-pln_2025-10-26"), get_report("rce-pln"))


def test_round_trip_keeps_types_and_download_time(tmp_path):
    cache = MonthCache(tmp_path)
    when = datetime(2025, 11, 5, 8, 30, tzinfo=UTC)
    cache.write("api", "rce-pln", date(2025, 10, 1), frame(), fetched_utc=when, first_day=date(2025, 10, 1),
                last_day=date(2025, 10, 31))
    cached = cache.read("api", "rce-pln", date(2025, 10, 1))
    assert cached.fetched_utc == when and cached.last_day == date(2025, 10, 31)
    assert cached.frame["start_utc"].dt.unit == "ns" and str(cached.frame["start_local"].dt.tz) == "Europe/Warsaw"
    assert cached.frame["business_date"].iloc[0] == date(2025, 10, 26)
    assert cached.frame["rce_pln"].tolist() == frame()["rce_pln"].tolist()


def test_unreadable_or_foreign_files_count_as_missing(tmp_path):
    cache = MonthCache(tmp_path)
    path = cache.path("api", "rce-pln", date(2025, 10, 1))
    path.parent.mkdir(parents=True)
    pq.write_table(pa.table({"x": [1]}), path)                       # no metadata of this package
    assert cache.read("api", "rce-pln", date(2025, 10, 1)) is None
    table = pa.table({"x": [1]}).replace_schema_metadata({b"pse_opendata": b'{"fetched_utc": "2025-01-01"}'})
    pq.write_table(table, path)                                       # metadata without all keys
    assert cache.read("api", "rce-pln", date(2025, 10, 1)) is None
    path.write_bytes(b"not parquet")
    assert cache.read("api", "rce-pln", date(2025, 10, 1)) is None


def test_clear_touches_only_cache_folders(tmp_path):
    cache = MonthCache(tmp_path)
    for source in ("api", "legacy"):
        cache.write(source, "x", date(2025, 1, 1), frame(), fetched_utc=datetime(2025, 2, 1, tzinfo=UTC),
                    first_day=date(2025, 1, 1), last_day=date(2025, 1, 31))
    own = tmp_path / "my_results.parquet"
    frame().to_parquet(own)
    assert cache.clear("legacy") == 1
    assert cache.clear() == 1
    assert own.exists()

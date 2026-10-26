"""Monthly Parquet cache.

One file per report and calendar month (business dates): ``<cache_dir>/<source>/<report>/<YYYY-MM>.parquet``,
with ``source`` = ``api`` or ``legacy``. Each file stores when it was downloaded, which decides whether the month is
final (see :attr:`pse_opendata.catalog.Report.revision_days`). Files are written atomically.

The default directory is ``$PSE_OPENDATA_CACHE`` if set, otherwise the user cache directory:
``%LOCALAPPDATA%\\pse-opendata\\cache`` on Windows, ``~/Library/Caches/pse-opendata`` on macOS and
``$XDG_CACHE_HOME/pse-opendata`` (``~/.cache/pse-opendata``) elsewhere.

Usage:
    cache = MonthCache(default_cache_dir())
    cache.write("api", "rce-pln", date(2025, 1, 1), frame, fetched_utc=now)
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from pse_opendata._version import __version__

META_KEY = b"pse_opendata"
SOURCES = ("api", "legacy")
DATETIME_COLUMNS = ["start_utc", "end_utc", "start_local", "end_local"]


def default_cache_dir() -> Path:
    env = os.environ.get("PSE_OPENDATA_CACHE")
    if env:
        return Path(env)
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return base / "pse-opendata" / "cache"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "pse-opendata"
    return Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "pse-opendata"


@dataclass(frozen=True)
class CachedMonth:
    frame: pd.DataFrame
    fetched_utc: datetime
    first_day: date
    last_day: date


class MonthCache:
    def __init__(self, root: Path | str):
        self.root = Path(root)

    def path(self, source: str, report: str, month: date) -> Path:
        return self.root / source / report / f"{month:%Y-%m}.parquet"

    def read(self, source: str, report: str, month: date) -> CachedMonth | None:
        """The cached month, or ``None`` when absent or unreadable."""
        path = self.path(source, report, month)
        if not path.exists():
            return None
        try:
            table = pq.read_table(path)
            meta = json.loads((table.schema.metadata or {})[META_KEY])
            fetched_utc = datetime.fromisoformat(meta["fetched_utc"])
            first_day = date.fromisoformat(meta["first_day"])
            last_day = date.fromisoformat(meta["last_day"])
            frame = table.to_pandas()
        except (OSError, KeyError, TypeError, ValueError, pa.ArrowException):
            return None
        for col in DATETIME_COLUMNS:
            if col in frame:
                frame[col] = frame[col].dt.as_unit("ns")
        return CachedMonth(frame=frame, fetched_utc=fetched_utc, first_day=first_day, last_day=last_day)

    def write(self, source: str, report: str, month: date, frame: pd.DataFrame, *, fetched_utc: datetime,
              first_day: date, last_day: date) -> Path:
        """Store the frame of one month; ``first_day``..``last_day`` are the business dates it covers."""
        path = self.path(source, report, month)
        path.parent.mkdir(parents=True, exist_ok=True)
        table = pa.Table.from_pandas(frame, preserve_index=False)
        meta = {"fetched_utc": fetched_utc.isoformat(), "first_day": first_day.isoformat(),
                "last_day": last_day.isoformat(), "report": report, "version": __version__}
        table = table.replace_schema_metadata({**(table.schema.metadata or {}), META_KEY: json.dumps(meta)})
        tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        pq.write_table(table, tmp)
        os.replace(tmp, path)
        return path

    def clear(self, source: str | None = None, report: str | None = None) -> int:
        """Delete cached files (all, one source, or one report of a source); returns how many were deleted.

        Only the ``api`` and ``legacy`` sub-folders are touched, so other files in the directory are safe.
        """
        sources = [source] if source else list(SOURCES)
        files = []
        for src in sources:
            base = self.root / src / report if report else self.root / src
            files += [f for f in base.glob("**/*.parquet") if f.is_file()] if base.exists() else []
        for f in files:
            f.unlink()
        return len(files)

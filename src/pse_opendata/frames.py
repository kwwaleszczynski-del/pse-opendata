"""Tidy frames with explicit interval times.

Every frame returned by this package has the columns

    start_utc, end_utc       interval start and end, tz-aware UTC
    start_local, end_local   the same instants in Europe/Warsaw (tz-aware, so DST days are unambiguous)
    business_date            business (trading) day in Polish local time, ``datetime.date``

followed by the row keys of the report (if any) and the value fields, one row per interval (and key), sorted by
``start_utc``. Time columns always have nanosecond resolution, whichever pandas version parsed them.

Usage:
    from pse_opendata.frames import to_hourly
    hourly = to_hourly(quarter_hourly_frame)
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

import pandas as pd

from pse_opendata.catalog import Field, Report

log = logging.getLogger("pse_opendata")

TZ = "Europe/Warsaw"
TIME_COLUMNS = ["start_utc", "end_utc", "start_local", "end_local", "business_date"]


def _as_ns(values: pd.Series | pd.DatetimeIndex) -> Any:
    return values.dt.as_unit("ns") if isinstance(values, pd.Series) else values.as_unit("ns")


def time_columns(start_utc: pd.Series | pd.DatetimeIndex, interval: pd.Timedelta) -> pd.DataFrame:
    """The five time columns for intervals starting at ``start_utc`` (tz-aware) and lasting ``interval``."""
    start = pd.Series(_as_ns(pd.DatetimeIndex(start_utc).tz_convert("UTC")))
    end = start + interval
    start_local = start.dt.tz_convert(TZ)
    return pd.DataFrame({
        "start_utc": start,
        "end_utc": end,
        "start_local": start_local,
        "end_local": end.dt.tz_convert(TZ),
        "business_date": start_local.dt.date,
    })


def parse_utc(values: pd.Series) -> pd.Series:
    """UTC time stamps written as text by PSE ("2025-10-26 01:15:00", sometimes without seconds)."""
    return _as_ns(pd.to_datetime(values, format="ISO8601", utc=True))


def _dtype(f: Field) -> str:
    return "float64" if f.dtype == "float" else "object"


def _values(raw: pd.DataFrame, f: Field) -> pd.Series:
    if f.name not in raw:
        return pd.Series(float("nan") if f.dtype == "float" else None, index=raw.index, dtype=_dtype(f))
    if f.dtype == "float":
        return pd.to_numeric(raw[f.name], errors="coerce").astype("float64")
    return raw[f.name].astype(object).where(raw[f.name].notna(), None)


def _ordered(fields: Sequence[Field], key: Sequence[str]) -> list[Field]:
    by_name = {f.name: f for f in fields}
    return [by_name[k] for k in key] + [f for f in fields if f.name not in key]


def empty_frame(fields: Sequence[Field], key: Sequence[str] = ()) -> pd.DataFrame:
    """A frame with no rows and the standard columns."""
    out = time_columns(pd.DatetimeIndex([], tz="UTC"), pd.Timedelta(0))
    out["business_date"] = out["business_date"].astype(object)
    for f in _ordered(fields, key):
        out[f.name] = pd.Series([], dtype=_dtype(f))
    return out


def tidy(frame: pd.DataFrame, key: Sequence[str] = (), dedupe: bool = True) -> pd.DataFrame:
    """Sort by start time (and key), drop duplicated intervals (and keys) keeping the last, reset the index."""
    cols = ["start_utc", *key]
    out = frame.sort_values(cols, kind="stable")
    if dedupe:
        out = out.drop_duplicates(cols, keep="last")
    return out.reset_index(drop=True)


def parse_records(records: list[dict[str, Any]], report: Report) -> pd.DataFrame:
    """Records of the reports API -> standard frame.

    The API stamps each row with the END of its interval (``dtime_utc``); the start is end minus the report
    resolution. Text fields like ``dtime`` or ``period`` are ignored: on the autumn DST day they read e.g.
    ``"02a:15"``, while ``dtime_utc`` is always unambiguous.
    """
    if not records:
        return empty_frame(report.fields, report.key)
    raw = pd.DataFrame.from_records(records)
    end = parse_utc(raw[report.time_field])
    out = time_columns(end - report.interval, report.interval)
    published = pd.to_datetime(raw["business_date"], format="ISO8601").dt.date
    mismatch = int((published != out["business_date"]).sum())
    if mismatch:
        log.warning("%s: %d rows whose business_date differs from the local date of the interval start",
                    report.name, mismatch)
        out["business_date"] = published
    for f in _ordered(report.fields, report.key):
        out[f.name] = _values(raw, f)
    return tidy(out, report.key, dedupe=report.unique_key)


def to_hourly(frame: pd.DataFrame, key: Sequence[str] = ()) -> pd.DataFrame:
    """Hourly means of a sub-hourly frame (e.g. 15-minute).

    An hour gets a value only when all its sub-intervals are present and not empty (four quarter-hours for a
    15-minute frame); otherwise the value is NaN. Text columns other than ``key`` are dropped. Hours are clock hours
    in UTC, which are also clock hours in Polish time (the offset is a whole number of hours).
    """
    if frame.empty:
        return frame.copy()
    step = (frame["end_utc"] - frame["start_utc"]).iloc[0]
    per_hour = int(pd.Timedelta("1h") / step)
    values = [c for c in frame.columns
              if c not in TIME_COLUMNS and c not in key and pd.api.types.is_numeric_dtype(frame[c])]
    hour = frame["start_utc"].dt.floor("h").rename("hour")
    groups = frame[values].groupby([hour, *(frame[k] for k in key)], sort=True)
    mean = groups.mean()
    count = groups.count()
    if per_hour > 1:
        mean = mean.where(count == per_hour)
    mean = mean.reset_index()
    out = time_columns(mean["hour"], pd.Timedelta("1h"))
    for k in key:
        out[k] = mean[k].to_numpy()
    for c in values:
        out[c] = mean[c].to_numpy()
    return tidy(out, key)

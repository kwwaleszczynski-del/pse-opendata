"""Legacy CSV export of www.pse.pl (hourly data until 2024-06-13).

Before the reports API, PSE published daily reports at www.pse.pl with a CSV export:

    https://www.pse.pl/getcsv/-/export/csv/<CODE>/data_od/<YYYYMMDD>/data_do/<YYYYMMDD>

What this module handles:

* cp1250 text, ``;`` separator, decimal comma, ``-`` for a missing value;
* dates written ``YYYY-MM-DD`` or ``YYYYMMDD`` depending on the report;
* hours 1..24 of the local day, hour 1 = 00:00-01:00; the extra autumn hour is ``2A`` (25 rows) and the spring day
  has 23 rows without hour ``2``. Rows are placed by their label, so a missing row leaves a gap instead of
  shifting the rest of the day;
* columns that changed over time (e.g. ``Generacja PI`` until 2020), matched by header name;
* the server is slow (about a minute for a month) and answers HTTP 429 to ranges longer than about a month and to
  quick series of requests, and rejects one-day ranges. Requests go one month at a time with a pause; a one-day
  range is widened and trimmed afterwards.

Usage:
    from pse_opendata.legacy_csv import parse_legacy_csv
    frame = parse_legacy_csv(text, get_legacy_report("PL_WYK_KSE"))
"""

from __future__ import annotations

import io
import logging
from datetime import date, timedelta

import pandas as pd

from pse_opendata._http import HttpClient
from pse_opendata.catalog import LegacyReport
from pse_opendata.exceptions import LegacyFormatError, PseApiError
from pse_opendata.frames import TZ, empty_frame, tidy, time_columns

log = logging.getLogger("pse_opendata")

LEGACY_URL = "https://www.pse.pl/getcsv/-/export/csv/{code}/data_od/{start:%Y%m%d}/data_do/{end:%Y%m%d}"
ENCODING = "cp1250"


def _labels(hours_in_day: int) -> list[str]:
    """Hour labels of a local day in time order: 23 (spring), 24 or 25 (autumn) hours."""
    if hours_in_day == 23:
        return ["1", *(str(h) for h in range(3, 25))]
    if hours_in_day == 25:
        return ["1", "2", "2A", *(str(h) for h in range(3, 25))]
    return [str(h) for h in range(1, 25)]


def _day_starts(days: pd.Series) -> pd.DataFrame:
    """Local midnight (as UTC) and number of hours of each distinct local day."""
    unique = pd.to_datetime(pd.Series(days.unique()), format="mixed")
    start = pd.DatetimeIndex(unique).tz_localize(TZ)
    end = pd.DatetimeIndex(unique + pd.Timedelta(days=1)).tz_localize(TZ)
    hours = ((end - start) / pd.Timedelta("1h")).astype(int)
    return pd.DataFrame({"midnight": start.tz_convert("UTC"), "hours": hours}, index=days.unique())


def parse_legacy_csv(text: str, report: LegacyReport) -> pd.DataFrame:
    """One CSV of the legacy export -> standard hourly frame (see :mod:`pse_opendata.frames`)."""
    if text.lstrip().startswith("<"):
        raise LegacyFormatError(f"{report.code}: the server returned an HTML page instead of CSV")
    raw = pd.read_csv(io.StringIO(text), sep=";", dtype=str, keep_default_na=False)
    if raw.shape[1] < 3 or raw.empty:
        if raw.shape[1] >= 2:
            return empty_frame(report.fields)
        raise LegacyFormatError(f"{report.code}: unexpected CSV header {list(raw.columns)}")
    headers = {c.header: c.field.name for c in report.columns}
    found = {col: headers.get(col.strip().lower()) for col in raw.columns[2:]}
    if not any(found.values()):
        raise LegacyFormatError(f"{report.code}: none of the expected columns in {list(raw.columns)}")
    day = raw.iloc[:, 0].str.strip()
    label = raw.iloc[:, 1].str.strip().str.upper().str.lstrip("0")
    days = _day_starts(day)
    offsets = []
    for d, lab in zip(day, label, strict=True):
        order = _labels(int(days.at[d, "hours"]))
        offsets.append(order.index(lab) if lab in order else -1)
    position = pd.Series(offsets, index=raw.index)
    bad = position < 0
    if bad.any():
        log.warning("%s: %d rows with an unexpected hour label skipped", report.code, int(bad.sum()))
    midnight = pd.DatetimeIndex(days.loc[day, "midnight"].to_numpy()).tz_convert("UTC")
    start = midnight + pd.to_timedelta(position.to_numpy(), unit="h")
    out = time_columns(start, pd.Timedelta("1h"))
    for col, name in found.items():
        if name:
            values = raw[col].str.strip().str.replace(",", ".", regex=False)
            out[name] = pd.to_numeric(values, errors="coerce").astype("float64").to_numpy()
    for f in report.fields:
        if f.name not in out:
            out[f.name] = float("nan")
    out = out[~bad.to_numpy()]
    return tidy(out[[*out.columns[:5], *report.field_names]])


def fetch_legacy(http: HttpClient, report: LegacyReport, start: date, end: date) -> pd.DataFrame:
    """Business dates ``start``..``end`` (inclusive) of one legacy report in a single request.

    Keep ranges to one month or less; the server rejects longer ones with HTTP 429. HTTP 404 means no data for the
    range and gives an empty frame.
    """
    lo, hi = start, end
    if lo == hi:   # one-day ranges are rejected
        hi = lo + timedelta(days=1)
        if hi > report.last_date:
            lo, hi = lo - timedelta(days=1), lo
    url = LEGACY_URL.format(code=report.code, start=lo, end=hi)
    try:
        frame = http.get(url, decode=lambda r: parse_legacy_csv(r.content.decode(ENCODING, errors="replace"), report))
    except PseApiError as e:
        if e.status == 404:
            log.info("%s %s..%s: no data (HTTP 404)", report.code, lo, hi)
            return empty_frame(report.fields)
        raise
    keep = (frame["business_date"] >= start) & (frame["business_date"] <= end)
    return frame[keep].reset_index(drop=True)

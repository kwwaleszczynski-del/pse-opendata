"""Long hourly series stitched from the legacy export (until 2024-06-13) and the reports API (from 2024-06-14).

The two sources do not overlap. The seam is local midnight of 2024-06-14 (2024-06-13 22:00 UTC). Legacy rows are
hourly already; API rows are averaged to clock hours that have all four quarter-hours (``to_hourly``).

Known differences at the seam:

* time stamps: the legacy export labels hours 1..24 (hour 1 = 00:00-01:00 local), the API stamps the END of each
  quarter-hour in UTC. Both are converted to interval starts here, so the seam has no time shift;
* level: API demand (``his-wlk-cal`` demand, equal to ``kse-load`` load_actual) runs below the legacy
  "Krajowe zapotrzebowanie na moc" (about 0.7% around the switch). ``rescale=True`` multiplies the API part by
  :func:`splice_factor`; by default nothing is rescaled.

Usage:
    from pse_opendata.stitch import SERIES, splice_factor
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd

from pse_opendata.catalog import API_START
from pse_opendata.frames import TZ

SEAM = pd.Timestamp(API_START).tz_localize(TZ).tz_convert("UTC")


@dataclass(frozen=True)
class StitchedSeries:
    name: str
    legacy_code: str
    legacy_field: str
    report: str
    field: str
    unit: str
    description: str


SERIES: dict[str, StitchedSeries] = {s.name: s for s in (
    StitchedSeries("rce", "PL_CENY_RYN_EN", "rce", "rce-pln", "rce_pln", "PLN/MWh",
                   "RCE price; hourly mean of the quarter-hour prices from 2025-10-01"),
    StitchedSeries("demand", "PL_WYK_KSE", "demand", "his-wlk-cal", "demand", "MW", "National power demand"),
    StitchedSeries("wind", "PL_GEN_WIATR", "wind", "his-wlk-cal", "wi", "MW", "Wind generation"),
    StitchedSeries("pv", "PL_GEN_WIATR", "pv", "his-wlk-cal", "pv", "MW", "PV generation (legacy data from 2020)"),
)}


def splice_factor(legacy: pd.Series, api: pd.Series, days: int = 14) -> float:
    """Level ratio legacy / API over ``days`` before and after the seam, matched by local weekday and hour.

    Both series are hourly values indexed by interval start (tz-aware). Only (weekday, hour) slots present on both
    sides are used. Multiply the API part by the result to bring it to the legacy level.
    """
    lo = legacy[(legacy.index >= SEAM - pd.Timedelta(days=days)) & (legacy.index < SEAM)].dropna()
    hi = api[(api.index >= SEAM) & (api.index < SEAM + pd.Timedelta(days=days))].dropna()
    if lo.empty or hi.empty:
        raise ValueError("no data on one side of the seam")

    def slot_means(s: pd.Series) -> pd.Series:
        local = s.index.tz_convert(TZ)
        return s.groupby([local.day_of_week, local.hour]).mean()

    a, b = slot_means(lo), slot_means(hi)
    common = a.index.intersection(b.index)
    return float(a[common].mean() / b[common].mean())


def clamp(start: date, end: date, first: date, last: date | None = None) -> tuple[date, date] | None:
    """``start``..``end`` limited to ``first``..``last``, or ``None`` if they do not overlap."""
    lo = max(start, first)
    hi = min(end, last) if last is not None else end
    return (lo, hi) if lo <= hi else None

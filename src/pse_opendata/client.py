"""The client: reports API, legacy export, monthly cache and stitched history.

Usage:
    from pse_opendata import Client
    client = Client(cache_dir="data/pse")
    rce = client.get("rce-pln", "2025-01-01", "2025-01-31")
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterator, Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Literal, TypeAlias

import pandas as pd
import requests

from pse_opendata._http import HttpClient
from pse_opendata.cache import CachedMonth, MonthCache, default_cache_dir
from pse_opendata.catalog import (
    API_START,
    LEGACY_END,
    Field,
    LegacyReport,
    Report,
    get_legacy_report,
    get_report,
)
from pse_opendata.exceptions import CacheMissError, PseApiError, UnknownFieldError
from pse_opendata.frames import TIME_COLUMNS, empty_frame, parse_records, tidy, to_hourly
from pse_opendata.legacy_csv import fetch_legacy
from pse_opendata.stitch import SEAM, SERIES, clamp, splice_factor

log = logging.getLogger("pse_opendata")

BASE_URL = "https://api.raporty.pse.pl/api"
MAX_PAGE = 100000   # largest $first the server accepts
DateLike: TypeAlias = date | datetime | str | pd.Timestamp
_DEFAULT: Any = object()


def to_date(value: DateLike) -> date:
    """A business date from a ``date``, ``datetime``, ``pandas.Timestamp`` or ISO string; times are ignored."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return pd.Timestamp(value).date()


def months(start: date, end: date) -> Iterator[tuple[date, date]]:
    """First and last day of each calendar month touching ``start``..``end``."""
    first = start.replace(day=1)
    while first <= end:
        nxt = (first + timedelta(days=32)).replace(day=1)
        yield first, nxt - timedelta(days=1)
        first = nxt


def _between(frame: pd.DataFrame, start: date, end: date) -> pd.DataFrame:
    keep = (frame["business_date"] >= start) & (frame["business_date"] <= end)
    return frame[keep.to_numpy()]


def _concat(frames: list[pd.DataFrame], fields: Sequence[Field], key: Sequence[str] = (),
            dedupe: bool = True) -> pd.DataFrame:
    frames = [f for f in frames if len(f)]
    if not frames:
        return empty_frame(fields, key)
    return tidy(pd.concat(frames, ignore_index=True), key, dedupe)


class Client:
    """Client for the public data of PSE.

    Args:
        cache_dir: directory of the monthly Parquet cache; default ``$PSE_OPENDATA_CACHE`` or the user cache
            directory (see :mod:`pse_opendata.cache`); ``None`` disables the cache.
        refresh: download again even months that the cache holds as final.
        offline: use the cache only; a missing month raises :class:`CacheMissError`.
        allow_stale: when a download fails, use the cached copy of the month (with a warning) instead of raising.
        revision_days: override the per-report number of days after the end of a month during which the cache
            re-downloads it (see :attr:`pse_opendata.catalog.Report.revision_days`).
        timeout: seconds per request (at least 180 for the legacy export).
        retries: retries per request, with exponential backoff, on network errors, HTTP 429 and 5xx.
        min_interval: pause in seconds between requests to the reports API.
        legacy_min_interval: pause in seconds between requests to the legacy export (it rate-limits hard).
        page_size: rows per page of the reports API (``$first``; the server allows at most 100000).
        session: a ``requests.Session`` to use (e.g. with a proxy); also how tests replay recorded responses.
        now: function returning the current time (UTC), for tests.
        sleep: replacement for ``time.sleep``, for tests.
    """

    def __init__(
        self,
        *,
        cache_dir: str | Path | None = _DEFAULT,
        refresh: bool = False,
        offline: bool = False,
        allow_stale: bool = False,
        revision_days: int | None = None,
        timeout: float = 60.0,
        retries: int = 4,
        min_interval: float = 0.2,
        legacy_min_interval: float = 15.0,
        page_size: int = 20000,
        session: requests.Session | None = None,
        now: Callable[[], datetime] | None = None,
        sleep: Callable[[float], None] | None = None,
    ):
        if cache_dir is _DEFAULT:
            cache_dir = default_cache_dir()
        self.cache = MonthCache(cache_dir) if cache_dir is not None else None
        self.refresh = refresh
        self.offline = offline
        self.allow_stale = allow_stale
        self.revision_days = revision_days
        self.page_size = page_size
        self._now = now or (lambda: datetime.now(UTC))
        session = session if session is not None else requests.Session()
        sleep = sleep or time.sleep
        self.http = HttpClient(session, timeout=timeout, retries=retries, min_interval=min_interval, sleep=sleep)
        self.legacy_http = HttpClient(session, timeout=max(timeout, 180.0), retries=retries, backoff=30.0,
                                      max_backoff=600.0, min_interval=legacy_min_interval, sleep=sleep)

    # --- reports API ----------------------------------------------------------------------------------------------

    def records(self, endpoint: str, *, filter: str | None = None, select: Sequence[str] | None = None,
                orderby: str | None = None, page_size: int | None = None,
                single_page: bool = False) -> list[dict[str, Any]]:
        """Raw records of any endpoint of the reports API, following ``nextLink`` pages.

        ``filter`` and ``orderby`` are OData expressions, e.g. ``filter="business_date eq '2025-01-01'"``.
        Works for endpoints that are not in the catalogue too; no parsing and no cache. ``single_page=True`` raises
        instead of following ``nextLink`` (for reports whose paging can skip rows).
        """
        query: dict[str, Any] = {"$first": page_size or self.page_size}
        if filter:
            query["$filter"] = filter
        if select:
            query["$select"] = ",".join(select)
        if orderby:
            query["$orderby"] = orderby
        params: dict[str, Any] | None = query          # the first request only; nextLink carries the query
        url: str | None = f"{BASE_URL}/{endpoint}"
        seen: set[str] = set()
        out: list[dict[str, Any]] = []
        while url:
            payload = self.http.get(url, params, decode=lambda r: r.json())
            if not isinstance(payload, dict) or not isinstance(payload.get("value"), list):
                raise PseApiError(f"unexpected response from {url}: no 'value' list", url=url)
            out.extend(payload["value"])
            next_link = payload.get("nextLink")
            if next_link and single_page:
                raise PseApiError(f"{endpoint}: more rows than one page of {query}; narrow the filter", url=url)
            if next_link in seen:
                raise PseApiError(f"paging loop at {next_link}", url=url)
            if next_link:
                seen.add(next_link)
            url, params = next_link, None
        return out

    def _by_day(self, report: Report, start: date, end: date, select: list[str]) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        day = start
        while day <= end:
            flt = f"business_date eq '{day:%Y-%m-%d}'"
            if report.unique_key:
                records += self.records(report.name, filter=flt, select=select)
            else:
                records += self.records(report.name, filter=flt, select=select, page_size=MAX_PAGE, single_page=True)
            day += timedelta(days=1)
        return records

    def _fetch_api(self, report: Report, start: date, end: date) -> pd.DataFrame:
        """Business dates ``start``..``end`` of one report; day by day if a long range fails with a server error.

        Reports with ``unique_key=False`` are always requested day by day in a single page.
        """
        select = [report.time_field, "business_date", *report.field_names]
        flt = f"business_date ge '{start:%Y-%m-%d}' and business_date le '{end:%Y-%m-%d}'"
        if not report.unique_key:
            records = self._by_day(report, start, end, select)
        else:
            try:
                records = self.records(report.name, filter=flt, select=select)
            except PseApiError as e:
                if start == end or e.status is None or e.status < 500:
                    raise
                log.warning("%s %s..%s failed (%s); retrying day by day", report.name, start, end, e)
                records = self._by_day(report, start, end, select)
        frame = parse_records(records, report)
        log.info("%s %s..%s: %d rows", report.name, start, end, len(frame))
        return frame

    def _read_cache(self, source: str, name: str, month: date, columns: Sequence[str]) -> CachedMonth | None:
        """Cached month, or ``None``; a file without all ``columns`` (older catalogue) counts as missing unless
        offline, where the missing columns are added empty."""
        cached = self.cache.read(source, name, month) if self.cache is not None else None
        if cached is None:
            return None
        missing = [c for c in columns if c not in cached.frame.columns]
        if not missing:
            return cached
        if not self.offline:
            return None
        log.warning("%s/%s %s: cached file lacks %s; filled with NaN", source, name, f"{month:%Y-%m}", missing)
        return CachedMonth(cached.frame.assign(**{c: float("nan") for c in missing}), cached.fetched_utc,
                           cached.first_day, cached.last_day)

    def _monthly(self, source: str, name: str, start: date, end: date,
                 fetch: Callable[[date, date], pd.DataFrame], revision_days: int | None,
                 available: tuple[date, date | None], columns: Sequence[str]) -> list[pd.DataFrame]:
        """Load ``start``..``end`` month by month through the cache.

        A whole month (or the part of it in which the source has data, ``available``) is downloaded and cached when
        the request covers it; part of a month is downloaded alone, unless a final cached copy exists.
        ``revision_days=None`` means the data never change (legacy export). ``columns``: fields a cached file must
        have.
        """
        frames = []
        for first, last in months(start, end):
            lo, hi = max(start, first), min(end, last)
            whole = lo == max(first, available[0]) and hi == min(last, available[1] or last)
            cached = self._read_cache(source, name, first, columns)
            if self.offline:
                if cached is None:
                    where = self.cache.root if self.cache is not None else "(cache disabled)"
                    raise CacheMissError(f"{source}/{name} {first:%Y-%m} is not in the cache {where}")
                frames.append(_between(cached.frame, lo, hi))
                continue
            if cached is not None and not self.refresh and self._final(cached, last, revision_days):
                frames.append(_between(cached.frame, lo, hi))
                continue
            fetched_utc = self._now()
            try:
                frame = fetch(first, last) if whole else fetch(lo, hi)
            except PseApiError as e:
                if self.allow_stale and cached is not None:
                    log.warning("%s %s %s: download failed (%s); using the copy cached on %s", source, name,
                                f"{first:%Y-%m}", e, f"{cached.fetched_utc:%Y-%m-%d %H:%M}")
                    frames.append(_between(cached.frame, lo, hi))
                    continue
                raise
            if whole and self.cache is not None:
                self.cache.write(source, name, first, frame, fetched_utc=fetched_utc, first_day=first, last_day=last)
            frames.append(_between(frame, lo, hi))
        return frames

    def _final(self, cached: CachedMonth, last_day: date, revision_days: int | None) -> bool:
        if revision_days is None:
            return True
        days = self.revision_days if self.revision_days is not None else revision_days
        return cached.fetched_utc.date() >= last_day + timedelta(days=days)

    def get(self, report: str, start: DateLike, end: DateLike | None = None, *,
            fields: Sequence[str] | None = None, dropna: bool = False) -> pd.DataFrame:
        """Data of one report for business dates ``start``..``end`` (inclusive, Polish local days).

        Returns a frame with ``start_utc``, ``end_utc``, ``start_local``, ``end_local``, ``business_date``, the
        row keys of the report (if any) and the value fields (all of them, or ``fields``), one row per interval.
        ``end`` defaults to ``start``. Dates before the first date of the report are skipped.
        ``dropna=True`` drops rows in which all requested values are empty (e.g. future intervals of today).
        """
        spec = get_report(report)
        selected = self._select(spec.fields, spec.key, fields, spec.name)
        lo, hi = to_date(start), to_date(end if end is not None else start)
        if lo > hi:
            raise ValueError(f"start {lo} is after end {hi}")
        span = clamp(lo, hi, spec.first_date)
        if span is None:
            frames: list[pd.DataFrame] = []
        else:
            if span[0] > lo:
                log.info("%s starts on %s; earlier dates skipped", spec.name, spec.first_date)
            frames = self._monthly("api", spec.name, span[0], span[1], lambda a, b: self._fetch_api(spec, a, b),
                                   spec.revision_days, (spec.first_date, None), spec.field_names)
        out = _concat(frames, spec.fields, spec.key, spec.unique_key)
        return self._finish(out, spec.key, selected, dropna)

    @staticmethod
    def _select(all_fields: Sequence[Field], key: Sequence[str], fields: Sequence[str] | None, name: str) -> list[str]:
        names = [f.name for f in all_fields]
        if fields is None:
            return [n for n in names if n not in key]
        if isinstance(fields, str):
            fields = [fields]
        unknown = [f for f in fields if f not in names]
        if unknown:
            raise UnknownFieldError(f"{name}: unknown fields {unknown}; available: {names}")
        return [f for f in fields if f not in key]

    @staticmethod
    def _finish(frame: pd.DataFrame, key: Sequence[str], selected: list[str], dropna: bool) -> pd.DataFrame:
        out = frame[[*TIME_COLUMNS, *key, *selected]]
        if dropna and selected:
            out = out.dropna(subset=selected, how="all")
        return out.reset_index(drop=True)

    # --- legacy export --------------------------------------------------------------------------------------------

    def legacy(self, code: str, start: DateLike, end: DateLike | None = None, *,
               fields: Sequence[str] | None = None) -> pd.DataFrame:
        """Hourly data of a legacy export report (e.g. ``"PL_WYK_KSE"``) for business dates ``start``..``end``.

        Same columns as :meth:`get`. Dates outside the range of the export are skipped. The server is slow (about
        a minute per month) and requests are spaced by ``legacy_min_interval`` seconds; months are cached for good.
        """
        spec = get_legacy_report(code)
        selected = self._select(spec.fields, (), fields, spec.code)
        lo, hi = to_date(start), to_date(end if end is not None else start)
        if lo > hi:
            raise ValueError(f"start {lo} is after end {hi}")
        span = clamp(lo, hi, spec.first_date, spec.last_date)
        frames = [] if span is None else self._monthly(
            "legacy", spec.code, span[0], span[1], lambda a, b: self._fetch_legacy(spec, a, b), None,
            (spec.first_date, spec.last_date), spec.field_names)
        return self._finish(_concat(frames, spec.fields), (), selected, False)

    def _fetch_legacy(self, spec: LegacyReport, start: date, end: date) -> pd.DataFrame:
        frame = fetch_legacy(self.legacy_http, spec, start, min(end, spec.last_date))
        log.info("%s %s..%s: %d hours", spec.code, start, end, len(frame))
        return frame

    # --- stitched history -----------------------------------------------------------------------------------------

    def history(self, series: str, start: DateLike, end: DateLike | None = None, *,
                rescale: bool = False) -> pd.DataFrame:
        """Hourly series across the switch from the legacy export to the reports API (2024-06-14).

        ``series`` is one of ``"rce"``, ``"demand"``, ``"wind"``, ``"pv"`` (see :data:`pse_opendata.stitch.SERIES`).
        Columns: the five time columns, the series (named like ``series``) and ``source`` (``"legacy"`` or
        ``"api"``). With ``rescale=True`` the API part is multiplied by :func:`splice_factor`, computed on the two
        weeks either side of the seam; the factor is stored in ``frame.attrs["splice_factor"]``.
        """
        if series not in SERIES:
            raise ValueError(f"unknown series {series!r}; available: {sorted(SERIES)}")
        spec = SERIES[series]
        lo, hi = to_date(start), to_date(end if end is not None else start)
        old = self._legacy_part(spec.legacy_code, spec.legacy_field, lo, hi)
        new = self._api_part(spec.report, spec.field, lo, hi)
        factor = 1.0
        if rescale and len(new):
            seam = SEAM.date()
            before = self._legacy_part(spec.legacy_code, spec.legacy_field, seam - timedelta(days=15), seam)
            after = self._api_part(spec.report, spec.field, seam, seam + timedelta(days=14))
            factor = splice_factor(before.set_index("start_utc")["value"], after.set_index("start_utc")["value"])
            new = new.assign(value=new["value"] * factor)
            log.info("%s: API part rescaled by %.4f", series, factor)
        parts = [p.assign(source=name) for p, name in ((old, "legacy"), (new, "api")) if len(p)]
        if parts:
            out = tidy(pd.concat(parts, ignore_index=True))
        else:
            out = empty_frame([Field("value", spec.description, spec.unit)]).assign(source=pd.Series(dtype=object))
        out = out.rename(columns={"value": series})[[*TIME_COLUMNS, series, "source"]]
        out.attrs["splice_factor"] = factor
        return out

    def _legacy_part(self, code: str, field: str, lo: date, hi: date) -> pd.DataFrame:
        if lo > LEGACY_END:
            return empty_frame([Field("value", "")])
        frame = self.legacy(code, lo, min(hi, LEGACY_END), fields=[field])
        frame = frame[frame["start_utc"] < SEAM]
        return frame.rename(columns={field: "value"})

    def _api_part(self, report: str, field: str, lo: date, hi: date) -> pd.DataFrame:
        if hi < API_START:
            return empty_frame([Field("value", "")])
        hourly = to_hourly(self.get(report, max(lo, API_START), hi, fields=[field]))
        hourly = hourly[hourly["start_utc"] >= SEAM]
        return hourly.rename(columns={field: "value"})

    # --- convenience ----------------------------------------------------------------------------------------------

    def rce(self, start: DateLike, end: DateLike | None = None, **kwargs: Any) -> pd.DataFrame:
        """RCE price, PLN/MWh (report ``rce-pln``)."""
        return self.get("rce-pln", start, end, **kwargs)

    def sdac(self, start: DateLike, end: DateLike | None = None, **kwargs: Any) -> pd.DataFrame:
        """SDAC day-ahead price for Poland, PLN/MWh (report ``csdac-pln``)."""
        return self.get("csdac-pln", start, end, **kwargs)

    def fundamentals(self, start: DateLike, end: DateLike | None = None, **kwargs: Any) -> pd.DataFrame:
        """Demand, generation (wind ``wi``, PV ``pv``, ...) and exchange balance, MW (report ``his-wlk-cal``)."""
        return self.get("his-wlk-cal", start, end, **kwargs)

    def imbalance_prices(self, start: DateLike, end: DateLike | None = None, **kwargs: Any) -> pd.DataFrame:
        """Imbalance price CEN and balancing energy prices, PLN/MWh (report ``crb-rozl``)."""
        return self.get("crb-rozl", start, end, **kwargs)

    def balancing_capacity(self, start: DateLike, end: DateLike | None = None,
                           procurement: Literal["primary", "supplementary"] = "primary") -> pd.DataFrame:
        """Balancing capacity prices and volumes per reserve product in one frame.

        ``procurement="primary"`` (day-ahead, hourly: ``cmbp-tp`` and ``mbp-tp``) or ``"supplementary"``
        (15-minute: ``cmbu-tu`` and ``mbu-tu``). Columns ``<product>_price`` (PLN/MW/h) and ``<product>_mw`` (MW),
        e.g. ``afrr_g_price`` and ``afrr_g_mw``.
        """
        reports = {"primary": ("cmbp-tp", "mbp-tp"), "supplementary": ("cmbu-tu", "mbu-tu")}
        if procurement not in reports:
            raise ValueError(f"procurement must be 'primary' or 'supplementary', not {procurement!r}")
        price_report, volume_report = reports[procurement]
        prices = self.get(price_report, start, end)
        volumes = self.get(volume_report, start, end)
        products = [c for c in prices.columns if c not in TIME_COLUMNS]
        prices = prices.rename(columns={p: f"{p}_price" for p in products})
        volumes = volumes.rename(columns={p: f"{p}_mw" for p in products})
        out = prices.merge(volumes, on=TIME_COLUMNS, how="outer")
        columns = [f"{p}_{kind}" for p in products for kind in ("price", "mw")]
        return out[[*TIME_COLUMNS, *columns]].sort_values("start_utc").reset_index(drop=True)

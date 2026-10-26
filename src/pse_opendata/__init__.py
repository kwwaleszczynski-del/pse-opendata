"""pse-opendata: unofficial client for the public data of PSE, the Polish transmission system operator.

Quick start:
    import pse_opendata as pse
    rce = pse.rce("2025-01-01", "2025-01-31")          # RCE price, 15-minute rows
    sys = pse.get("his-wlk-cal", "2025-06-01", fields=["demand", "wi", "pv"])
    demand = pse.history("demand", "2019-01-01", "2025-12-31")   # legacy export + API, hourly

Module-level functions use a shared default :class:`Client` (default cache directory, see
:mod:`pse_opendata.cache`); pass ``client=Client(...)`` to any of them to change the settings.
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from pse_opendata._version import __version__
from pse_opendata.catalog import LEGACY_REPORTS, REPORTS, Field, LegacyReport, Report, get_legacy_report, get_report
from pse_opendata.client import Client, DateLike
from pse_opendata.exceptions import (
    CacheMissError,
    LegacyFormatError,
    PseApiError,
    PseError,
    UnknownFieldError,
    UnknownReportError,
)
from pse_opendata.frames import TIME_COLUMNS, to_hourly
from pse_opendata.stitch import splice_factor

logging.getLogger("pse_opendata").addHandler(logging.NullHandler())

__all__ = [
    "LEGACY_REPORTS", "REPORTS", "TIME_COLUMNS", "CacheMissError", "Client", "Field", "LegacyFormatError",
    "LegacyReport", "PseApiError", "PseError", "Report", "UnknownFieldError", "UnknownReportError", "__version__",
    "balancing_capacity", "default_client", "fundamentals", "get", "get_legacy_report", "get_report", "history",
    "imbalance_prices", "legacy", "rce", "reports", "sdac", "splice_factor", "to_hourly",
]

_default: Client | None = None


def default_client() -> Client:
    """The shared client used by the module-level functions (created on first use)."""
    global _default
    if _default is None:
        _default = Client()
    return _default


def get(report: str, start: DateLike, end: DateLike | None = None, *, client: Client | None = None,
        **kwargs: Any) -> pd.DataFrame:
    """Data of a report of the reports API; see :meth:`Client.get`."""
    return (client or default_client()).get(report, start, end, **kwargs)


def legacy(code: str, start: DateLike, end: DateLike | None = None, *, client: Client | None = None,
           **kwargs: Any) -> pd.DataFrame:
    """Hourly data of the legacy CSV export; see :meth:`Client.legacy`."""
    return (client or default_client()).legacy(code, start, end, **kwargs)


def history(series: str, start: DateLike, end: DateLike | None = None, *, client: Client | None = None,
            **kwargs: Any) -> pd.DataFrame:
    """Hourly series stitched from the legacy export and the API; see :meth:`Client.history`."""
    return (client or default_client()).history(series, start, end, **kwargs)


def rce(start: DateLike, end: DateLike | None = None, *, client: Client | None = None, **kwargs: Any) -> pd.DataFrame:
    """RCE price (``rce-pln``); see :meth:`Client.rce`."""
    return (client or default_client()).rce(start, end, **kwargs)


def sdac(start: DateLike, end: DateLike | None = None, *, client: Client | None = None, **kwargs: Any) -> pd.DataFrame:
    """SDAC price for Poland (``csdac-pln``); see :meth:`Client.sdac`."""
    return (client or default_client()).sdac(start, end, **kwargs)


def fundamentals(start: DateLike, end: DateLike | None = None, *, client: Client | None = None,
                 **kwargs: Any) -> pd.DataFrame:
    """Demand, generation and exchange (``his-wlk-cal``); see :meth:`Client.fundamentals`."""
    return (client or default_client()).fundamentals(start, end, **kwargs)


def imbalance_prices(start: DateLike, end: DateLike | None = None, *, client: Client | None = None,
                     **kwargs: Any) -> pd.DataFrame:
    """Imbalance and balancing energy prices (``crb-rozl``); see :meth:`Client.imbalance_prices`."""
    return (client or default_client()).imbalance_prices(start, end, **kwargs)


def balancing_capacity(start: DateLike, end: DateLike | None = None, *, client: Client | None = None,
                       **kwargs: Any) -> pd.DataFrame:
    """Balancing capacity prices and volumes; see :meth:`Client.balancing_capacity`."""
    return (client or default_client()).balancing_capacity(start, end, **kwargs)


def reports(legacy: bool = False) -> pd.DataFrame:
    """The catalogue as a frame: one row per report of the reports API (or of the legacy export)."""
    if legacy:
        rows = [{"code": r.code, "title": r.title, "title_pl": r.title_pl, "resolution": r.resolution,
                 "first_date": r.first_date, "last_date": r.last_date, "fields": ", ".join(r.field_names),
                 "page": r.page} for r in LEGACY_REPORTS.values()]
    else:
        rows = [{"name": r.name, "title": r.title, "title_pl": r.title_pl, "group": r.group,
                 "resolution": r.resolution, "first_date": r.first_date, "revision_days": r.revision_days,
                 "fields": ", ".join(r.field_names), "verified": r.verified, "url": r.url} for r in REPORTS.values()]
    return pd.DataFrame(rows)

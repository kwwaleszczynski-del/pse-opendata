"""Consistency of the report catalogue and of the generated catalogue page."""

from __future__ import annotations

import importlib.util
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from pse_opendata.catalog import API_START, LEGACY_END, LEGACY_REPORTS, REPORTS, get_legacy_report, get_report
from pse_opendata.exceptions import UnknownReportError

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("report", REPORTS.values(), ids=list(REPORTS))
def test_report_entries(report):
    names = report.field_names
    assert len(names) == len(set(names)) > 0
    assert set(report.key) <= set(names)
    assert pd.Timedelta(report.resolution) in (pd.Timedelta("15min"), pd.Timedelta("1h"))
    assert report.first_date >= API_START
    assert report.revision_days >= 1
    assert report.url == f"https://raporty.pse.pl/report/{report.name}"
    for f in report.fields:
        assert f.description and f.dtype in ("float", "str")
        assert (f.unit is None) == (f.dtype == "str")


@pytest.mark.parametrize("report", LEGACY_REPORTS.values(), ids=list(LEGACY_REPORTS))
def test_legacy_entries(report):
    assert report.last_date == LEGACY_END == date(2024, 6, 13)
    assert report.first_date < report.last_date
    assert all(c.header == c.header.lower() for c in report.columns)
    assert report.page.startswith("https://www.pse.pl/dane-systemowe/")


def test_lookup_errors_name_the_known_reports():
    assert get_report("rce-pln").title.startswith("Market price")
    with pytest.raises(UnknownReportError, match="his-wlk-cal"):
        get_report("his-wlk")
    with pytest.raises(UnknownReportError, match="PL_WYK_KSE"):
        get_legacy_report("PL_WYK")


def test_catalogue_page_is_up_to_date():
    spec = importlib.util.spec_from_file_location("gen_docs", ROOT / "scripts" / "gen_docs.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    page = (ROOT / "docs" / "reports.md").read_text(encoding="utf-8")
    assert page == module.render(), "run: python scripts/gen_docs.py"

"""Tests against the real PSE servers; run with ``pytest --live tests/live``. Light on purpose (a few requests)."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest
import requests

import pse_opendata as pse
from pse_opendata.catalog import OPENAPI, REPORTS

pytestmark = pytest.mark.live
DAY = date.today() - timedelta(days=7)


@pytest.fixture(scope="module")
def client() -> pse.Client:
    return pse.Client(cache_dir=None)


@pytest.fixture(scope="module")
def openapi() -> dict:
    r = requests.get(OPENAPI, timeout=120, headers={"User-Agent": "pse-opendata live tests"})
    r.raise_for_status()
    return r.json()


@pytest.mark.parametrize("name", list(REPORTS))
def test_catalogue_matches_the_openapi_description(openapi, name):
    report = REPORTS[name]
    properties = openapi["components"]["schemas"][name]["properties"]
    assert {report.time_field, "business_date", *report.field_names} <= set(properties)
    key_paths = [p for p in openapi["paths"] if p.startswith(f"/{name}/")]
    for k in report.key:
        assert any(f"/{k}/" in p for p in key_paths), f"{k} is not part of the entity key"


def test_rce_of_a_recent_day(client):
    frame = client.rce(DAY)
    assert len(frame) in (92, 96, 100)
    assert frame["rce_pln"].notna().all()
    assert (frame["end_utc"] - frame["start_utc"] == pd.Timedelta("15min")).all()


def test_demand_equals_kse_load(client):
    a = client.get("his-wlk-cal", DAY, fields=["demand"])
    b = client.get("kse-load", DAY, fields=["load_actual"])
    joined = a.merge(b, on="start_utc")
    assert len(joined) == len(a)
    assert (joined["demand"] - joined["load_actual"]).abs().max() < 1e-6


def test_offers_are_complete(client):
    frame = client.get("popmb-rmb", DAY)
    raw = client.records("popmb-rmb", filter=f"business_date eq '{DAY:%Y-%m-%d}'", page_size=100000)
    assert len(frame) == len(raw) > 0


def test_legacy_export_answers(client):
    frame = client.legacy("PL_CENY_RYN_EN", "2023-10-28", "2023-10-29")
    assert len(frame) == 24 + 25
    assert frame["rce"].notna().all()

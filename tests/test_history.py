"""Stitching the legacy export (until 2024-06-13) and the reports API (from 2024-06-14)."""

from __future__ import annotations

import pandas as pd
import pytest

from pse_opendata.stitch import SEAM, splice_factor

from conftest import FakeResponse, api_pages, endpoint_of, legacy_bytes, serve_pages, utc

API_PART = serve_pages(api_pages("his-wlk-cal_2024-06-14_2024-06-27"))


def handler(calls: list[str]):
    def answer(url, params):
        calls.append(url)
        if "getcsv" in url:
            return FakeResponse(content=legacy_bytes("PL_WYK_KSE_2024-05-29_2024-06-13"))
        assert endpoint_of(url) == "his-wlk-cal"
        return API_PART(url, params)
    return answer


def test_seam_is_local_midnight_of_2024_06_14():
    assert utc("2024-06-13 22:00") == SEAM


def test_demand_is_continuous_across_the_seam(make_client):
    client, _ = make_client(handler([]), cache=False)
    frame = client.history("demand", "2024-06-10", "2024-06-17")
    assert len(frame) == 8 * 24
    assert (frame["start_utc"].diff().dropna() == pd.Timedelta("1h")).all()
    last_legacy = frame[frame["source"] == "legacy"].iloc[-1]
    first_api = frame[frame["source"] == "api"].iloc[0]
    assert last_legacy["start_local"].isoformat() == "2024-06-13T23:00:00+02:00"
    assert first_api["start_local"].isoformat() == "2024-06-14T00:00:00+02:00"
    assert first_api["start_utc"] == last_legacy["end_utc"]
    assert list(frame.columns) == ["start_utc", "end_utc", "start_local", "end_local", "business_date",
                                   "demand", "source"]
    assert frame.attrs["splice_factor"] == 1.0


def test_api_hours_are_means_of_four_quarter_hours(make_client):
    client, _ = make_client(handler([]), cache=False)
    frame = client.history("demand", "2024-06-14", "2024-06-14")
    quarters = client.get("his-wlk-cal", "2024-06-14", fields=["demand"])
    assert len(frame) == 24 and set(frame["source"]) == {"api"}
    assert frame["demand"].iloc[0] == pytest.approx(quarters["demand"].iloc[:4].mean())


def test_only_the_needed_source_is_requested(make_client):
    calls: list[str] = []
    client, _ = make_client(handler(calls), cache=False)
    client.history("demand", "2024-06-01", "2024-06-05")
    assert calls and all("getcsv" in c for c in calls)
    calls.clear()
    client.history("demand", "2024-06-20", "2024-06-21")
    assert calls and all("raporty.pse.pl" in c for c in calls)


def test_rescale_brings_the_api_part_to_the_legacy_level(make_client):
    client, _ = make_client(handler([]), cache=False)
    plain = client.history("demand", "2024-06-10", "2024-06-17")
    scaled = client.history("demand", "2024-06-10", "2024-06-17", rescale=True)
    factor = scaled.attrs["splice_factor"]
    assert 0.98 < factor < 1.03 and factor != 1.0
    api = plain["source"] == "api"
    assert scaled.loc[api, "demand"].to_numpy() == pytest.approx(plain.loc[api, "demand"].to_numpy() * factor)
    assert (scaled.loc[~api, "demand"] == plain.loc[~api, "demand"]).all()


def test_splice_factor_matches_weekday_and_hour():
    hours = pd.date_range(SEAM - pd.Timedelta(days=14), SEAM + pd.Timedelta(days=14), freq="1h", inclusive="left")
    shape = pd.Series([1000.0 + 100 * (t.hour % 7) + 50 * t.weekday() for t in hours.tz_convert("Europe/Warsaw")],
                      index=hours)
    legacy = shape[shape.index < SEAM] * 1.1
    api = shape[shape.index >= SEAM]
    assert splice_factor(legacy, api) == pytest.approx(1.1)
    with pytest.raises(ValueError):
        splice_factor(legacy.iloc[:0], api)


def test_unknown_series(make_client):
    client, _ = make_client(handler([]), cache=False)
    with pytest.raises(ValueError, match="available"):
        client.history("prices", "2024-06-01")

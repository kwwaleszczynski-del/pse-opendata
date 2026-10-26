"""Legacy CSV export: hour labels and DST days, date formats, changing columns, requests and cache."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from pse_opendata.catalog import get_legacy_report
from pse_opendata.exceptions import LegacyFormatError
from pse_opendata.legacy_csv import parse_legacy_csv

from conftest import FakeResponse, legacy_bytes, legacy_text, stamps, utc

WYK = get_legacy_report("PL_WYK_KSE")
WIATR = get_legacy_report("PL_GEN_WIATR")


def assert_hourly_run(frame: pd.DataFrame) -> None:
    assert frame["start_utc"].is_monotonic_increasing and frame["start_utc"].is_unique
    assert (frame["start_utc"].diff().dropna() == pd.Timedelta("1h")).all()


def test_autumn_day_has_25_hours_with_2a_in_place():
    frame = parse_legacy_csv(legacy_text("PL_WYK_KSE_2023-10-28_2023-10-30"), WYK)
    assert frame.groupby("business_date").size().tolist() == [24, 25, 24]
    assert_hourly_run(frame)
    day = frame[frame["business_date"] == date(2023, 10, 29)]
    # labels 1, 2, 2A, 3: local 00:00 and 01:00 CEST, then 02:00 CEST and 02:00 CET
    assert stamps(day["start_local"].iloc[:4]) == ["2023-10-29T00:00:00+02:00", "2023-10-29T01:00:00+02:00",
                                                   "2023-10-29T02:00:00+02:00", "2023-10-29T02:00:00+01:00"]
    assert day["demand"].iloc[:4].tolist() == [15314.075, 14555.413, 14120.625, 13747.963]
    assert day["end_local"].iloc[-1].isoformat() == "2023-10-30T00:00:00+01:00"


def test_spring_day_has_23_hours():
    frame = parse_legacy_csv(legacy_text("PL_WYK_KSE_2023-03-25_2023-03-27"), WYK)
    assert frame.groupby("business_date").size().tolist() == [24, 23, 24]
    assert_hourly_run(frame)
    day = frame[frame["business_date"] == date(2023, 3, 26)]
    assert stamps(day["start_local"].iloc[:2]) == ["2023-03-26T00:00:00+01:00", "2023-03-26T01:00:00+01:00"]
    assert day["start_local"].iloc[2].isoformat() == "2023-03-26T03:00:00+02:00"


def test_hour_one_is_the_first_hour_of_the_local_day():
    frame = parse_legacy_csv(legacy_text("PL_WYK_KSE_2023-10-28_2023-10-30"), WYK)
    assert frame["start_utc"].iloc[0] == utc("2023-10-27 22:00")       # 2023-10-28 00:00 CEST
    assert frame["end_utc"].iloc[0] == utc("2023-10-27 23:00")


def test_compact_dates_and_price_report():
    frame = parse_legacy_csv(legacy_text("PL_CENY_RYN_EN_2023-10-28_2023-10-30"), get_legacy_report("PL_CENY_RYN_EN"))
    assert len(frame) == 73
    assert frame["business_date"].iloc[0] == date(2023, 10, 28)
    assert frame["rce"].iloc[0] == 423.0
    prices = parse_legacy_csv(legacy_text("PL_CENY_ROZL_RB_2023-10-28_2023-10-30"),
                              get_legacy_report("PL_CENY_ROZL_RB"))
    assert prices["cor"].isna().all()                  # column not published after 2020
    assert prices[["cro", "cros", "croz"]].notna().all().all()


def test_columns_that_existed_only_in_older_files():
    frame = parse_legacy_csv(legacy_text("PL_WYK_KSE_2010-01-01_2010-01-03"), WYK)
    assert list(frame.columns[5:]) == WYK.field_names
    assert frame["demand"].iloc[0] == pytest.approx(15217.575)
    assert np.isnan(frame["pi"].iloc[0])               # '-' in the file
    recent = parse_legacy_csv(legacy_text("PL_WYK_KSE_2023-10-28_2023-10-30"), WYK)
    assert recent[["pi", "irz"]].isna().all().all()    # columns gone from 2021
    old = parse_legacy_csv(legacy_text("PL_CENY_ROZL_RB_2019-01-01_2019-01-03"), get_legacy_report("PL_CENY_ROZL_RB"))
    assert "cor" in old and old["cro"].notna().all()


def test_pv_is_empty_before_it_was_published():
    frame = parse_legacy_csv(legacy_text("PL_GEN_WIATR_2020-04-09_2020-04-11"), WIATR)
    by_day = frame.groupby("business_date")["pv"].apply(lambda s: s.notna().any())
    assert by_day.to_dict() == {date(2020, 4, 9): False, date(2020, 4, 10): True, date(2020, 4, 11): True}
    assert frame["wind"].notna().all()


def test_a_missing_row_leaves_a_gap_instead_of_shifting_the_day():
    text = legacy_text("PL_WYK_KSE_2023-10-28_2023-10-30")
    lines = text.splitlines()
    removed = [line for line in lines if line.startswith("2023-10-28;5;")]
    frame = parse_legacy_csv("\n".join(line for line in lines if line not in removed), WYK)
    full = parse_legacy_csv(text, WYK)
    assert len(frame) == len(full) - 1
    missing = set(full["start_utc"]) - set(frame["start_utc"])
    assert missing == {utc("2023-10-28 02:00")}            # hour 5 = 04:00-05:00 CEST
    merged = full.merge(frame, on="start_utc", suffixes=("", "_cut"))
    assert (merged["demand"] == merged["demand_cut"]).all()


def test_html_instead_of_csv_is_rejected():
    with pytest.raises(LegacyFormatError, match="HTML"):
        parse_legacy_csv(legacy_text("PL_WYK_KSE_2008-01-01_2008-01-03_404"), WYK)
    with pytest.raises(LegacyFormatError, match="expected columns"):
        parse_legacy_csv("Data;Godzina;Something else\n2023-01-01;1;5\n", WYK)


def csv_handler(name: str, calls: list[str] | None = None, status: int = 200):
    def handler(url, params):
        if calls is not None:
            calls.append(url)
        return FakeResponse(status, content=legacy_bytes(name))
    return handler


def test_one_day_request_is_widened_and_trimmed(make_client):
    calls: list[str] = []
    client, _ = make_client(csv_handler("PL_WYK_KSE_2023-10-28_2023-10-30", calls), cache=False)
    frame = client.legacy("PL_WYK_KSE", "2023-10-29")
    assert calls == ["https://www.pse.pl/getcsv/-/export/csv/PL_WYK_KSE/data_od/20231029/data_do/20231030"]
    assert set(frame["business_date"]) == {date(2023, 10, 29)} and len(frame) == 25


def test_last_day_of_the_export_is_widened_backwards(make_client):
    calls: list[str] = []
    client, _ = make_client(csv_handler("PL_WYK_KSE_2024-05-29_2024-06-13", calls), cache=False)
    frame = client.legacy("PL_WYK_KSE", "2024-06-13", "2024-07-31")
    assert calls == ["https://www.pse.pl/getcsv/-/export/csv/PL_WYK_KSE/data_od/20240612/data_do/20240613"]
    assert set(frame["business_date"]) == {date(2024, 6, 13)}


def test_month_requests_and_permanent_cache(make_client):
    calls: list[str] = []
    client, _ = make_client(csv_handler("PL_WYK_KSE_2023-10-28_2023-10-30", calls))
    client.legacy("PL_WYK_KSE", "2023-10-01", "2023-11-30")
    assert calls == [
        "https://www.pse.pl/getcsv/-/export/csv/PL_WYK_KSE/data_od/20231001/data_do/20231031",
        "https://www.pse.pl/getcsv/-/export/csv/PL_WYK_KSE/data_od/20231101/data_do/20231130",
    ]
    again = client.legacy("PL_WYK_KSE", "2023-10-29", fields=["demand"])
    assert len(calls) == 2                                   # legacy months never change
    assert list(again.columns) == ["start_utc", "end_utc", "start_local", "end_local", "business_date", "demand"]


def test_404_means_no_data_and_dates_outside_the_export_are_skipped(make_client):
    calls: list[str] = []
    client, _ = make_client(csv_handler("PL_WYK_KSE_2008-01-01_2008-01-03_404", calls, status=404), cache=False)
    assert client.legacy("PL_WYK_KSE", "2009-01-01", "2009-01-03").empty
    assert len(calls) == 1
    assert client.legacy("PL_WYK_KSE", "2008-01-01", "2008-12-31").empty
    assert client.legacy("PL_WYK_KSE", "2024-06-14", "2024-12-31").empty
    assert len(calls) == 1


def test_rate_limit_answer_is_retried(make_client):
    answers = [FakeResponse(429, content=b"<html>Too Many Requests</html>"),
               FakeResponse(200, content=legacy_bytes("PL_CENY_RYN_EN_2023-10-28_2023-10-30"))]
    client, session = make_client(lambda u, p: answers.pop(0), cache=False)
    frame = client.legacy("PL_CENY_RYN_EN", "2023-10-28", "2023-10-30")
    assert len(frame) == 73 and len(session.calls) == 2

"""Parsing of reports API records: interval times, DST days, empty values, multi-row reports."""

from __future__ import annotations

import logging
from datetime import date

import pandas as pd
import pytest

from pse_opendata.catalog import get_report
from pse_opendata.frames import TIME_COLUMNS, empty_frame, parse_records, to_hourly

from conftest import api_records, stamps, utc


def assert_contiguous(frame: pd.DataFrame, step: str) -> None:
    """Every interval starts where the previous one ended, in UTC."""
    assert frame["start_utc"].is_monotonic_increasing and frame["start_utc"].is_unique
    assert (frame["end_utc"] - frame["start_utc"] == pd.Timedelta(step)).all()
    assert (frame["start_utc"].iloc[1:].to_numpy() == frame["end_utc"].iloc[:-1].to_numpy()).all()


def test_dtime_utc_is_the_interval_end():
    frame = parse_records(api_records("rce-pln_2025-10-26"), get_report("rce-pln"))
    first = api_records("rce-pln_2025-10-26")[0]
    assert first["dtime_utc"] == "2025-10-25 22:15:00"
    assert frame["start_utc"].iloc[0] == utc("2025-10-25 22:00")
    assert frame["end_utc"].iloc[0] == utc("2025-10-25 22:15")
    assert frame["start_local"].iloc[0].isoformat() == "2025-10-26T00:00:00+02:00"


def test_autumn_dst_day_has_100_unambiguous_quarter_hours():
    frame = parse_records(api_records("rce-pln_2025-10-26"), get_report("rce-pln"))
    assert len(frame) == 100
    assert_contiguous(frame, "15min")
    assert set(frame["business_date"]) == {date(2025, 10, 26)}
    assert frame["end_local"].iloc[-1].isoformat() == "2025-10-27T00:00:00+01:00"
    # the local hour 02:00-03:00 happens twice, first in summer time (+02:00), then in winter time (+01:00)
    at_two = frame.loc[frame["start_local"].map(lambda t: t.strftime("%H:%M")) == "02:00", "start_local"]
    assert stamps(at_two) == ["2025-10-26T02:00:00+02:00", "2025-10-26T02:00:00+01:00"]


def test_spring_dst_day_has_92_quarter_hours_and_no_two_oclock():
    frame = parse_records(api_records("rce-pln_2025-03-30"), get_report("rce-pln"))
    assert len(frame) == 92
    assert_contiguous(frame, "15min")
    assert not (frame["start_local"].map(lambda t: t.hour) == 2).any()
    assert frame["start_utc"].iloc[0] == utc("2025-03-29 23:00")
    assert frame["end_utc"].iloc[-1] == utc("2025-03-30 22:00")


@pytest.mark.parametrize(("name", "rows"), [("cmbp-tp_2025-10-26", 25), ("cmbp-tp_2025-03-30", 23)])
def test_hourly_report_on_dst_days(name, rows):
    frame = parse_records(api_records(name), get_report("cmbp-tp"))
    assert len(frame) == rows
    assert_contiguous(frame, "1h")
    assert frame["start_local"].iloc[0].strftime("%Y-%m-%d %H:%M") == f"{name[-10:]} 00:00"
    assert frame["rr_d"].isna().all()           # RR down is never procured


def test_time_columns_are_tz_aware_and_nanosecond():
    frame = parse_records(api_records("rce-pln_2025-10-26"), get_report("rce-pln"))
    assert list(frame.columns[:5]) == TIME_COLUMNS
    for col, tz in [("start_utc", "UTC"), ("end_utc", "UTC"), ("start_local", "Europe/Warsaw"),
                    ("end_local", "Europe/Warsaw")]:
        assert str(frame[col].dt.tz) == tz
        assert frame[col].dt.unit == "ns"      # normalised by the package, whatever pandas parsed


def test_timestamps_without_seconds():
    records = api_records("poze-redoze_2024-09-24_first_rows")
    assert records[0]["dtime_utc"] == "2024-09-23 22:15"
    frame = parse_records(records, get_report("poze-redoze"))
    assert frame["start_utc"].iloc[0] == utc("2024-09-23 22:00")


def test_empty_values_are_kept_as_nan():
    records = api_records("his-wlk-cal_2026-10-26_partial")
    future = sum(r["demand"] is None for r in records)     # quarter-hours after the moment of recording
    assert future > 0
    frame = parse_records(records, get_report("his-wlk-cal"))
    assert len(frame) == 96
    assert frame["demand"].isna().sum() == future
    assert frame["demand"].iloc[-future:].isna().all()
    assert frame["jgw1"].isna().all()               # field not requested in the fixture -> NaN column


def test_empty_response_gives_standard_columns():
    frame = parse_records([], get_report("popmb-rmb"))
    assert frame.empty
    assert list(frame.columns) == [*TIME_COLUMNS, "reserve_type", "com", "pom", "comrr"]
    assert str(frame["start_local"].dt.tz) == "Europe/Warsaw"
    assert list(empty_frame(get_report("rce-pln").fields).columns) == [*TIME_COLUMNS, "rce_pln"]


def test_identical_offers_are_all_kept():
    records = api_records("popmb-rmb_2025-10-02_first_hour")
    frame = parse_records(records, get_report("popmb-rmb"))
    assert len(frame) == len(records) == 310
    assert frame.duplicated(["start_utc", "reserve_type", "com", "pom", "comrr"]).any()
    assert frame["reserve_type"].str.endswith(("ᴳ", "ᴰ")).all()
    assert (frame["end_utc"] - frame["start_utc"] == pd.Timedelta("1h")).all()


def test_rows_with_a_key_are_sorted_by_interval_and_key():
    frame = parse_records(api_records("przeplywy-mocy_2025-10-02_first_interval"), get_report("przeplywy-mocy"))
    assert len(frame) == 14
    assert frame["section_code"].tolist() == sorted(frame["section_code"])
    assert frame["start_utc"].nunique() == 1


def test_duplicated_intervals_keep_the_last_row():
    records = api_records("rce-pln_2025-10-26")[:2]
    repeated = [*records, {**records[0], "rce_pln": 1.0}]
    frame = parse_records(repeated, get_report("rce-pln"))
    assert len(frame) == 2
    assert frame["rce_pln"].iloc[0] == 1.0


def test_business_date_that_disagrees_with_the_interval_is_reported(caplog):
    record = {**api_records("rce-pln_2025-10-26")[0], "business_date": "2025-10-25"}
    with caplog.at_level(logging.WARNING, logger="pse_opendata"):
        frame = parse_records([record], get_report("rce-pln"))
    assert "business_date differs" in caplog.text
    assert frame["business_date"].iloc[0] == date(2025, 10, 25)


def test_to_hourly_repeats_the_hourly_price_and_averages_quarter_hours():
    frame = parse_records(api_records("rce-pln_2025-09-30_2025-10-01"), get_report("rce-pln"))
    q = frame.set_index("start_utc")["rce_pln"]
    hourly = to_hourly(frame)
    assert len(hourly) == 48
    assert_contiguous(hourly, "1h")
    h = hourly.set_index("start_utc")["rce_pln"]
    # until 2025-09-30 the API repeats the hourly RCE in the four quarter-hours
    sept = q[q.index < utc("2025-09-30 22:00")]
    assert (sept.groupby(sept.index.floor("h")).nunique() == 1).all()
    assert h[utc("2025-09-30 10:00")] == q[utc("2025-09-30 10:00")]
    # from 2025-10-01 quarter-hours differ and the hourly value is their mean
    hour = utc("2025-10-01 10:00")
    quarters = q[(q.index >= hour) & (q.index < hour + pd.Timedelta("1h"))]
    assert quarters.nunique() > 1
    assert h[hour] == pytest.approx(quarters.mean())


def test_to_hourly_leaves_incomplete_hours_empty():
    frame = parse_records(api_records("rce-pln_2025-10-26"), get_report("rce-pln"))
    hourly = to_hourly(frame.drop(index=[5]))       # one quarter-hour of the second hour missing
    assert len(hourly) == 25
    assert pd.isna(hourly["rce_pln"].iloc[1])
    assert hourly["rce_pln"].iloc[[0, 2]].notna().all()
    assert hourly["start_local"].iloc[-1].isoformat() == "2025-10-26T23:00:00+01:00"

"""Directional cross-border flows, keyed hourly means and publication times (fixes of 0.2.1)."""

from __future__ import annotations

import pandas as pd
import pytest

import pse_opendata as pse
from pse_opendata.catalog import get_report
from pse_opendata.frames import TIME_COLUMNS, net_flows, parse_records, to_hourly

from conftest import api_pages, api_records, serve_pages, utc


def flows() -> pd.DataFrame:
    return parse_records(api_records("przeplywy-mocy_2025-10-02_first_interval"), get_report("przeplywy-mocy"))


def test_flow_sections_are_directional_rows():
    frame = flows()
    inbound = frame["section_code"].str.endswith("-PL")
    assert (frame.loc[inbound, "value"] >= 0).all() and (frame.loc[~inbound, "value"] <= 0).all()
    by_code = frame.set_index("section_code")["value"]
    assert by_code["CZ-PL"] > 0 and by_code["PL-CZ"] < 0          # both directions at once on the Czech border
    value = get_report("przeplywy-mocy").field("value").description
    assert "PL-X" in value and "sum of both rows" in value


def test_net_flows_adds_both_directions_per_neighbour():
    frame = flows()
    borders = net_flows(frame)
    assert list(borders.columns) == [*TIME_COLUMNS, "neighbour", "import", "export", "net"]
    assert borders["neighbour"].tolist() == ["CZ", "DE", "LT", "SE", "SK", "UA"]     # UA_DOB counted as UA
    cz = borders.set_index("neighbour").loc["CZ"]
    assert cz["import"] == pytest.approx(216.8) and cz["export"] == pytest.approx(-169.2)
    assert cz["net"] == pytest.approx(47.6)
    assert borders["net"].sum() == pytest.approx(frame["value"].sum())
    assert borders["start_utc"].iloc[0] == utc("2025-10-01 22:00")
    assert pse.net_flows is net_flows
    with pytest.raises(ValueError, match="przeplywy-mocy"):
        net_flows(frame.drop(columns="section_code"))
    assert net_flows(frame.iloc[:0]).empty


def test_to_hourly_refuses_several_rows_per_interval_without_a_key():
    frame = flows()
    with pytest.raises(ValueError, match="key="):
        to_hourly(frame)
    assert len(to_hourly(frame, key=["section_code"])) == len(frame)     # one hour, one row per section


def test_unit_consumption_is_described_as_negative():
    assert "negative" in get_report("gen-jw").field("value").description


def test_publication_time_is_parsed():
    records = api_records("kse-load_2026-08-10_publication")
    frame = parse_records(records, get_report("kse-load"))
    assert str(frame["publication_utc"].dt.tz) == "UTC"
    assert frame["publication_utc"].iloc[0] == pd.Timestamp(records[0]["publication_ts_utc"], tz="UTC")
    assert (frame["publication_utc"].dt.date > frame["business_date"]).all()     # forecast published the day after
    old = parse_records(api_records("rce-pln_2025-10-26"), get_report("rce-pln"))
    assert old["publication_utc"].isna().all()                                    # field not in the record: NaT


def test_publication_column_only_on_request(make_client):
    client, _ = make_client(serve_pages(api_pages("kse-load_2026-08-10_publication")), cache=False)
    plain = client.get("kse-load", "2026-08-10")
    assert "publication_utc" not in plain
    with_pub = client.get("kse-load", "2026-08-10", fields=["load_fcst"], publication=True)
    assert list(with_pub.columns) == [*TIME_COLUMNS, "load_fcst", "publication_utc"]
    assert with_pub["publication_utc"].iloc[0] == pd.Timestamp("2026-08-11 01:05:10.516", tz="UTC")

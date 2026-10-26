"""Client: paging, validation, monthly cache, offline and stale modes, day-by-day fallbacks."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pandas as pd
import pytest

import pse_opendata as pse
from pse_opendata import client as pse_client
from pse_opendata.exceptions import CacheMissError, PseApiError, UnknownFieldError, UnknownReportError

from conftest import (
    API,
    Clock,
    FakeResponse,
    api_pages,
    endpoint_of,
    filter_of,
    records_for,
    serve_pages,
    serve_records,
)

JAN_2025 = {"rce-pln": records_for("rce_pln", date(2025, 1, 1), date(2025, 1, 31))}


def test_follows_next_link_pages(make_client):
    pages = api_pages("rce-pln_2025-10-02_paged")
    assert len(pages) == 3 and pages[0]["nextLink"]
    client, session = make_client(serve_pages(pages), cache=False)
    frame = client.rce("2025-10-02")
    assert len(frame) == 96
    assert [url for url, _ in session.calls][1:] == [p["nextLink"] for p in pages[:-1]]
    first_params = session.calls[0][1]
    assert first_params["$filter"] == "business_date ge '2025-10-02' and business_date le '2025-10-02'"
    assert first_params["$select"] == "dtime_utc,business_date,rce_pln"
    assert first_params["$first"] == 20000


def test_detects_a_paging_loop(make_client):
    page = {"value": [], "nextLink": f"{API}/rce-pln?$after=abc"}
    client, _ = make_client(lambda url, params: FakeResponse(payload=page), cache=False)
    with pytest.raises(PseApiError, match="paging loop"):
        client.records("rce-pln")


def test_unexpected_payload_is_an_error(make_client):
    client, _ = make_client(lambda url, params: FakeResponse(payload={"error": "?"}), cache=False)
    with pytest.raises(PseApiError, match="no 'value' list"):
        client.records("rce-pln")


def test_unknown_report_and_field(make_client):
    client, session = make_client(serve_records(JAN_2025), cache=False)
    with pytest.raises(UnknownReportError, match="rce-pln"):
        client.get("rce", "2025-01-01")
    with pytest.raises(UnknownFieldError, match="available"):
        client.get("rce-pln", "2025-01-01", fields=["price"])
    with pytest.raises(ValueError, match="after end"):
        client.get("rce-pln", "2025-01-02", "2025-01-01")
    assert session.calls == []


def test_fields_selection_and_date_types(make_client):
    client, _ = make_client(serve_records(JAN_2025), cache=False)
    frame = client.get("rce-pln", datetime(2025, 1, 3, 15, 30), pd.Timestamp("2025-01-04"), fields="rce_pln")
    assert list(frame.columns) == [*pse.TIME_COLUMNS, "rce_pln"]
    assert sorted(set(frame["business_date"])) == [date(2025, 1, 3), date(2025, 1, 4)]
    assert len(frame) == 192


def test_dates_before_the_report_starts_are_skipped(make_client):
    client, session = make_client(serve_records(JAN_2025), cache=False)
    frame = client.get("rce-pln", "2024-01-01", "2024-03-31")
    assert frame.empty and session.calls == []


def test_dropna_removes_rows_without_values(make_client):
    client, _ = make_client(serve_pages(api_pages("his-wlk-cal_2026-10-26_partial")), cache=False)
    full = client.get("his-wlk-cal", "2026-10-26", fields=["demand", "wi", "pv"])
    kept = client.get("his-wlk-cal", "2026-10-26", fields=["demand", "wi", "pv"], dropna=True)
    assert len(full) == 96
    assert len(kept) == full["demand"].notna().sum() < 96


def test_whole_month_is_cached_and_reused_once_final(make_client, tmp_path):
    clock = Clock(datetime(2025, 2, 2, 12, tzinfo=UTC))      # 2 days after the month: not final yet
    client, session = make_client(serve_records(JAN_2025), now=clock)
    first = client.rce("2025-01-01", "2025-01-31")
    assert len(first) == 31 * 96 and len(session.calls) == 1
    assert (tmp_path / "cache" / "api" / "rce-pln" / "2025-01.parquet").exists()
    client.rce("2025-01-10", "2025-01-12")                                # cached copy is not final -> download
    assert len(session.calls) == 2
    clock.when = datetime(2025, 2, 10, tzinfo=UTC)
    client.rce("2025-01-01", "2025-01-31")                                # downloaded again, now final
    assert len(session.calls) == 3
    again = client.rce("2025-01-10", "2025-01-12")                        # served from the cache
    assert len(session.calls) == 3
    assert len(again) == 3 * 96
    assert again["start_utc"].dt.unit == "ns" and str(again["start_local"].dt.tz) == "Europe/Warsaw"
    assert again["business_date"].iloc[0] == date(2025, 1, 10)


def test_revision_window_depends_on_the_report(make_client):
    settlement = {"en-rozl": records_for("balance", date(2025, 1, 1), date(2025, 1, 31))}
    clock = Clock(datetime(2025, 3, 1, tzinfo=UTC))
    client, session = make_client(serve_records(settlement), now=clock)
    client.get("en-rozl", "2025-01-01", "2025-01-31")
    client.get("en-rozl", "2025-01-01", "2025-01-31")
    assert len(session.calls) == 2                                        # republished for up to 240 days
    # same cache directory: the copy downloaded 29 days after the month is final with a 10-day window
    override, calls = make_client(serve_records(settlement), now=clock, revision_days=10)
    override.get("en-rozl", "2025-01-01", "2025-01-31")
    assert calls.calls == []


def test_partial_month_is_not_cached(make_client, tmp_path):
    client, session = make_client(serve_records(JAN_2025))
    client.rce("2025-01-05", "2025-01-06")
    assert not (tmp_path / "cache" / "api" / "rce-pln").exists()
    assert session.calls[0][1]["$filter"] == "business_date ge '2025-01-05' and business_date le '2025-01-06'"


def test_offline_mode(make_client):
    client, _ = make_client(serve_records(JAN_2025))
    client.rce("2025-01-01", "2025-01-31")
    offline, session = make_client(lambda u, p: FakeResponse(500), offline=True)
    assert len(offline.rce("2025-01-02")) == 96
    with pytest.raises(CacheMissError, match="2025-02"):
        offline.rce("2025-02-01")
    assert session.calls == []


def test_stale_copy_is_used_only_when_allowed(make_client):
    client, _ = make_client(serve_records(JAN_2025), now=Clock(datetime(2025, 2, 1, tzinfo=UTC)))
    client.rce("2025-01-01", "2025-01-31")
    failing, _ = make_client(lambda u, p: FakeResponse(503), retries=1)
    with pytest.raises(PseApiError):
        failing.rce("2025-01-01", "2025-01-31")
    stale, _ = make_client(lambda u, p: FakeResponse(503), retries=1, allow_stale=True)
    assert len(stale.rce("2025-01-01", "2025-01-31")) == 31 * 96


def test_refresh_downloads_final_months_again(make_client):
    client, session = make_client(serve_records(JAN_2025))
    client.rce("2025-01-01", "2025-01-31")
    client.rce("2025-01-01", "2025-01-31")
    assert len(session.calls) == 1
    refreshing, calls = make_client(serve_records(JAN_2025), refresh=True)
    refreshing.rce("2025-01-01", "2025-01-31")
    assert len(calls.calls) == 1


def test_server_error_on_a_long_range_falls_back_to_days(make_client):
    serve = serve_records(JAN_2025)

    def handler(url, params):
        if " ge " in filter_of(url, params):
            return FakeResponse(500)
        return serve(url, params)

    client, session = make_client(handler, cache=False, retries=0)
    frame = client.rce("2025-01-01", "2025-01-03")
    assert len(frame) == 3 * 96
    assert [filter_of(u, p) for u, p in session.calls[1:]] == [
        f"business_date eq '2025-01-0{d}'" for d in (1, 2, 3)]


def test_reports_without_unique_rows_are_fetched_day_by_day_in_one_page(make_client):
    rows = [{**r, "reserve_type": "aFRRᴳ", "pom": 1.0, "com": 10.0, "comrr": None}
            for r in records_for("x", date(2025, 1, 1), date(2025, 1, 2), step="1h")]
    client, session = make_client(serve_records({"popmb-rmb": rows + rows}), cache=False)
    frame = client.get("popmb-rmb", "2025-01-01", "2025-01-02")
    assert len(frame) == 2 * len(rows)                                     # identical offers are kept
    assert [p["$first"] for _, p in session.calls] == [100000, 100000]
    assert [filter_of(u, p) for u, p in session.calls] == ["business_date eq '2025-01-01'",
                                                           "business_date eq '2025-01-02'"]


def test_single_page_reports_refuse_to_page(make_client):
    page = {"value": [], "nextLink": f"{API}/popmb-rmb?$after=abc"}
    client, _ = make_client(lambda u, p: FakeResponse(payload=page), cache=False)
    with pytest.raises(PseApiError, match="more rows than one page"):
        client.get("popmb-rmb", "2025-01-01")


def test_balancing_capacity_joins_prices_and_volumes(make_client):
    products = ["fcr_g", "fcr_d", "afrr_g", "afrr_d", "mfrrd_g", "mfrrd_d", "rr_g", "rr_d"]

    def rows(scale):
        base = records_for("fcr_g", date(2025, 1, 1), date(2025, 1, 1), step="1h")
        return [{**r, **{p: scale * (i + 1) for i, p in enumerate(products)}} for r in base]

    client, _ = make_client(serve_records({"cmbp-tp": rows(10.0), "mbp-tp": rows(1.0)}), cache=False)
    frame = client.balancing_capacity("2025-01-01")
    assert len(frame) == 24
    assert list(frame.columns[5:9]) == ["fcr_g_price", "fcr_g_mw", "fcr_d_price", "fcr_d_mw"]
    assert frame["afrr_g_price"].iloc[0] == 30.0 and frame["afrr_g_mw"].iloc[0] == 3.0
    with pytest.raises(ValueError, match="procurement"):
        client.balancing_capacity("2025-01-01", procurement="basic")


def test_convenience_functions_pick_their_reports(make_client):
    seen = []
    serve = serve_records({name: records_for("v", date(2025, 1, 1), date(2025, 1, 1))
                           for name in ("rce-pln", "csdac-pln", "his-wlk-cal", "crb-rozl")})

    def handler(url, params):
        seen.append(endpoint_of(url))
        return serve(url, params)

    client, _ = make_client(handler, cache=False)
    client.rce("2025-01-01")
    client.sdac("2025-01-01")
    client.fundamentals("2025-01-01")
    client.imbalance_prices("2025-01-01")
    pse.get("rce-pln", "2025-01-01", client=client)
    assert seen == ["rce-pln", "csdac-pln", "his-wlk-cal", "crb-rozl", "rce-pln"]


def test_reports_table():
    table = pse.reports()
    assert {"rce-pln", "his-wlk-cal", "crb-rozl", "popmb-rmb"} <= set(table["name"])
    assert set(pse.reports(legacy=True)["code"]) == {"PL_WYK_KSE", "PL_GEN_WIATR", "PL_CENY_RYN_EN",
                                                     "PL_CENY_ROZL_RB"}


def test_cached_file_without_a_catalogue_field(make_client, tmp_path):
    client, _ = make_client(serve_records(JAN_2025))
    old = client.rce("2025-01-01", "2025-01-31").drop(columns="rce_pln")     # as written by an older catalogue
    client.cache.write("api", "rce-pln", date(2025, 1, 1), old, fetched_utc=datetime(2025, 6, 1, tzinfo=UTC),
                       first_day=date(2025, 1, 1), last_day=date(2025, 1, 31))
    fresh, session = make_client(serve_records(JAN_2025))
    assert fresh.rce("2025-01-02")["rce_pln"].notna().all()                  # downloaded again
    assert len(session.calls) == 1
    offline, _ = make_client(lambda u, p: FakeResponse(500), offline=True)
    assert offline.rce("2025-01-02")["rce_pln"].isna().all()                 # offline: kept, empty column


def test_time_zone_aware_dates_are_polish_business_days():
    assert pse_client.to_date(datetime(2025, 3, 1, 23, 30, tzinfo=UTC)) == date(2025, 3, 2)
    assert pse_client.to_date(pd.Timestamp("2025-03-01 22:59", tz="UTC")) == date(2025, 3, 1)
    assert pse_client.to_date("2025-03-01T23:30+00:00") == date(2025, 3, 2)
    assert pse_client.to_date(datetime(2025, 3, 1, 23, 30)) == date(2025, 3, 1)      # naive: taken as is


def test_empty_months_are_not_cached(make_client, tmp_path):
    client, session = make_client(lambda u, p: FakeResponse(payload={"value": []}))
    assert client.rce("2025-01-01", "2025-01-31").empty
    assert not (tmp_path / "cache" / "api" / "rce-pln").exists()


def test_cache_write_errors_do_not_lose_the_download(make_client, monkeypatch, caplog):
    client, _ = make_client(serve_records(JAN_2025))

    def fail(*args, **kwargs):
        raise PermissionError("read-only")

    monkeypatch.setattr(client.cache, "write", fail)
    assert len(client.rce("2025-01-01", "2025-01-31")) == 31 * 96
    assert "could not write the cache" in caplog.text

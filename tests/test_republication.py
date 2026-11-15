"""Republication check of final cached months and completeness of cached copies (fixes of 0.2.1)."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pandas as pd

import pse_opendata as pse

from conftest import Clock, FakeResponse, records_for, serve_records

JAN_2025 = {"rce-pln": records_for("rce_pln", date(2025, 1, 1), date(2025, 1, 31))}


def handler(rows: list[dict], latest: list[str | None], checks: list[dict]):
    """Serve month data; answer the republication check (``$orderby`` query) with ``latest[0]``."""
    serve = serve_records({"his-wlk-cal": rows})

    def answer(url, params):
        if params and params.get("$orderby") == "publication_ts_utc desc":
            checks.append(params)
            value = [] if latest[0] is None else [{"publication_ts_utc": latest[0]}]
            return FakeResponse(payload={"value": value})
        return serve(url, params)
    return answer


def published(first: date, last: date, when: str) -> list[dict]:
    return [{**r, "publication_ts_utc": when} for r in records_for("demand", first, last)]


def test_final_month_republished_later_is_downloaded_again(make_client):
    rows = published(date(2025, 10, 1), date(2025, 10, 31), "2025-11-01 01:00:00.000")
    latest: list[str | None] = ["2025-11-01 01:00:00.000"]
    checks: list[dict] = []
    clock = Clock(datetime(2026, 1, 5, tzinfo=UTC))                 # 66 days after the month: final
    seed, _ = make_client(handler(rows, latest, checks), now=clock, check_republished=True)
    seed.fundamentals("2025-10-01", "2025-10-31")
    cached = seed.cache.read("api", "his-wlk-cal", date(2025, 10, 1))
    assert cached.published_utc == pd.Timestamp("2025-11-01 01:00", tz="UTC")

    again, _ = make_client(handler(rows, latest, checks), now=clock, check_republished=True)
    again.fundamentals("2025-10-01", "2025-10-31")
    assert [m.status for m in again.loads] == ["cached"] and len(checks) == 1    # nothing newer: one check
    again.fundamentals("2025-10-05")
    assert len(checks) == 1                                                    # a client checks a month once

    latest[0] = "2026-01-19 19:01:56.023"                                      # bulk republication at PSE
    fresh, _ = make_client(handler(rows, latest, checks), now=clock, check_republished=True)
    fresh.fundamentals("2025-10-05")                                           # part of the month requested
    assert [m.status for m in fresh.loads] == ["downloaded"]
    assert fresh.cache.read("api", "his-wlk-cal", date(2025, 10, 1)).fetched_utc == clock.when   # whole month


def test_files_without_publication_time_compare_with_the_download_time(make_client):
    rows = records_for("demand", date(2025, 10, 1), date(2025, 10, 31))          # no publication_ts_utc
    checks: list[dict] = []
    clock = Clock(datetime(2026, 1, 5, tzinfo=UTC))
    seed, _ = make_client(handler(rows, [None], checks), now=clock)
    seed.fundamentals("2025-10-01", "2025-10-31")
    assert seed.cache.read("api", "his-wlk-cal", date(2025, 10, 1)).published_utc is None
    latest: list[str | None] = ["2026-01-04 10:00:00"]                          # before the download: up to date
    client, _ = make_client(handler(rows, latest, checks), now=clock, check_republished=True)
    client.fundamentals("2025-10-01", "2025-10-31")
    assert [m.status for m in client.loads] == ["cached"]
    latest[0] = "2026-01-19 19:00:00"                                          # after the download: stale
    later, _ = make_client(handler(rows, latest, checks), now=clock, check_republished=True)
    later.fundamentals("2025-10-01", "2025-10-31")
    assert [m.status for m in later.loads] == ["downloaded"]


def test_one_request_checks_several_months(make_client):
    rows = published(date(2025, 8, 1), date(2025, 10, 31), "2025-11-01 01:00:00")
    latest: list[str | None] = ["2025-11-01 01:00:00"]
    checks: list[dict] = []
    clock = Clock(datetime(2026, 2, 1, tzinfo=UTC))
    seed, _ = make_client(handler(rows, latest, checks), now=clock)
    seed.fundamentals("2025-08-01", "2025-10-31")
    client, _ = make_client(handler(rows, latest, checks), now=clock, check_republished=True)
    client.fundamentals("2025-08-01", "2025-10-31")
    assert len(checks) == 1
    assert checks[0]["$filter"] == "business_date ge '2025-08-01' and business_date le '2025-10-31'"
    assert checks[0]["$first"] == 1
    assert {m.status for m in client.loads} == {"cached"}


def test_the_check_is_optional_and_never_breaks_a_load(make_client, caplog):
    rows = published(date(2025, 10, 1), date(2025, 10, 31), "2025-11-01 01:00:00")
    clock = Clock(datetime(2026, 1, 5, tzinfo=UTC))
    seed, _ = make_client(handler(rows, [None], []), now=clock)
    month = seed.fundamentals("2025-10-01", "2025-10-31")
    assert len(month) == 31 * 96 + 4                                     # 25-hour day on 2025-10-26

    def failing(url, params):
        if params and params.get("$orderby"):
            return FakeResponse(500)
        raise AssertionError("no data request expected")

    client, session = make_client(failing, now=clock, check_republished=True, retries=3)
    assert len(client.fundamentals("2025-10-01", "2025-10-31")) == len(month)
    assert "could not check PSE for republished data" in caplog.text
    assert len(session.calls) == 1                                       # the check is not retried
    offline, calls = make_client(failing, now=clock, check_republished=True, offline=True)
    offline.fundamentals("2025-10-01", "2025-10-31")
    assert calls.calls == []
    off, calls = make_client(failing, now=clock)                         # default: no check
    off.fundamentals("2025-10-01", "2025-10-31")
    assert calls.calls == []


def test_check_modes_per_report():
    assert pse.get_report("popmb-rmb").republication_check == "none"
    assert pse.get_report("gen-jw").republication_check == "month"
    assert pse.get_report("his-wlk-cal").republication_check == "span"
    assert pse.Client(cache_dir=None).check_republished is False      # opt-in in 0.2.x


def test_offline_copy_fetched_mid_month_is_flagged_incomplete(make_client, caplog):
    clock = Clock(datetime(2025, 1, 15, 12, tzinfo=UTC))
    client, _ = make_client(serve_records(JAN_2025), now=clock)
    client.rce("2025-01-01", "2025-01-31")                          # current month, cached on 15 January
    offline, _ = make_client(lambda u, p: FakeResponse(500), offline=True)
    offline.rce("2025-01-01", "2025-01-10")
    assert [m.complete for m in offline.loads] == [True]
    offline.rce("2025-01-01", "2025-01-31")
    assert offline.loads[-1].complete is False
    assert "before the end of 2025-01-31" in caplog.text
    stale, _ = make_client(lambda u, p: FakeResponse(503), retries=0, allow_stale=True)
    stale.rce("2025-01-01", "2025-01-31")
    assert stale.loads[-1].status == "stale" and stale.loads[-1].complete is False

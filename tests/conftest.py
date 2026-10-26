"""Shared test helpers: recorded PSE responses, a fake HTTP session and synthetic API records.

Nothing here touches the network. Tests marked ``live`` run only with ``pytest --live``.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import pandas as pd
import pytest
import requests

from pse_opendata import Client

FIXTURES = Path(__file__).parent / "fixtures"
API = "https://api.raporty.pse.pl/api"


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--live", action="store_true", help="run tests that call the real PSE servers")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if config.getoption("--live"):
        return
    skip = pytest.mark.skip(reason="needs --live")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)


def api_pages(name: str) -> list[dict[str, Any]]:
    """Recorded pages of a reports API response (see scripts/record_fixtures.py)."""
    return json.loads((FIXTURES / "api" / f"{name}.json").read_text(encoding="utf-8"))["pages"]


def api_records(name: str) -> list[dict[str, Any]]:
    return [row for page in api_pages(name) for row in page["value"]]


def legacy_text(name: str) -> str:
    return (FIXTURES / "legacy" / f"{name}.csv").read_bytes().decode("cp1250", errors="replace")


def legacy_bytes(name: str) -> bytes:
    return (FIXTURES / "legacy" / f"{name}.csv").read_bytes()


def utc(text: str) -> pd.Timestamp:
    return pd.Timestamp(text, tz="UTC")


def stamps(values: pd.Series) -> list[str]:
    """Time stamps as ISO text, so comparisons do not depend on the datetime resolution of pandas."""
    return [t.isoformat() for t in values]


class FakeResponse:
    def __init__(self, status: int = 200, payload: Any = None, content: bytes | None = None,
                 headers: dict[str, str] | None = None):
        self.status_code = status
        self.headers = headers or {}
        self.reason = {200: "OK", 400: "Bad Request", 404: "Not Found", 429: "Too Many Requests",
                       500: "Internal Server Error", 503: "Service Unavailable"}.get(status, "")
        if content is None:
            content = json.dumps(payload).encode("utf-8") if payload is not None else b""
        self.content = content

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", "replace")

    def json(self) -> Any:
        return json.loads(self.content)


Handler = Callable[[str, dict[str, Any] | None], FakeResponse]


class FakeSession:
    """Stands in for ``requests.Session``; ``handler(url, params)`` returns a :class:`FakeResponse`."""

    def __init__(self, handler: Handler):
        self.handler = handler
        self.calls: list[tuple[str, dict[str, Any] | None]] = []

    def get(self, url: str, params: dict[str, Any] | None = None, timeout: float | None = None,
            headers: dict[str, str] | None = None) -> FakeResponse:
        self.calls.append((url, dict(params) if params else None))
        result = self.handler(url, params)
        if isinstance(result, Exception):
            raise result
        return result


def endpoint_of(url: str) -> str:
    return urlparse(url).path.rsplit("/", 1)[-1]


def filter_of(url: str, params: dict[str, Any] | None) -> str:
    if params and "$filter" in params:
        return params["$filter"]
    return parse_qs(urlparse(url).query).get("$filter", [""])[0]


def serve_pages(pages: list[dict[str, Any]]) -> Handler:
    """Serve recorded pages in order: the first request gets page 0, a ``nextLink`` gets the page it points to."""
    by_link = {p["nextLink"]: pages[i + 1] for i, p in enumerate(pages[:-1]) if p.get("nextLink")}

    def handler(url: str, params: dict[str, Any] | None) -> FakeResponse:
        return FakeResponse(payload=by_link.get(url, pages[0]))

    return handler


def records_for(field: str, start: date, end: date, step: str = "15min",
                value: Callable[[pd.Timestamp], float] | None = None, time_field: str = "dtime_utc") -> list[dict]:
    """Synthetic API records for business dates start..end: one row per interval, stamped with the interval end."""
    first = pd.Timestamp(start).tz_localize("Europe/Warsaw")
    last = (pd.Timestamp(end) + pd.Timedelta(days=1)).tz_localize("Europe/Warsaw")
    starts = pd.date_range(first, last, freq=step, inclusive="left")
    rows = []
    for t in starts:
        end_utc = (t + pd.Timedelta(step)).tz_convert("UTC")
        rows.append({time_field: end_utc.strftime("%Y-%m-%d %H:%M:%S"),
                     "business_date": t.strftime("%Y-%m-%d"),
                     field: value(t) if value else float(t.hour)})
    return rows


def serve_records(by_endpoint: dict[str, list[dict]]) -> Handler:
    """Answer ``business_date`` range or day filters from synthetic records, one page each."""
    def handler(url: str, params: dict[str, Any] | None) -> FakeResponse:
        rows = by_endpoint[endpoint_of(url)]
        flt = filter_of(url, params)
        dates = [part.split("'")[1] for part in flt.split(" and ")]
        lo, hi = (dates[0], dates[0]) if " eq " in flt else (dates[0], dates[1])
        return FakeResponse(payload={"value": [r for r in rows if lo <= r["business_date"] <= hi]})
    return handler


class Clock:
    """A settable 'now' for cache finality tests."""

    def __init__(self, when: datetime):
        self.when = when

    def __call__(self) -> datetime:
        return self.when


@pytest.fixture
def make_client(tmp_path: Path) -> Callable[..., tuple[Client, FakeSession]]:
    """Client with a fake session, a temporary cache, no real sleeping and a fixed 'now'."""
    def make(handler: Handler, *, now: datetime | None = None, cache: bool = True, **kwargs: Any):
        session = FakeSession(handler)
        client = Client(session=session, cache_dir=tmp_path / "cache" if cache else None,
                        now=now or Clock(datetime(2026, 10, 26, 12, tzinfo=UTC)),
                        sleep=lambda s: None, min_interval=0, legacy_min_interval=0, **kwargs)
        return client, session
    return make


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("network access in an offline test")
    monkeypatch.setattr(requests.Session, "get", refuse)

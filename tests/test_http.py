"""Retries, backoff, Retry-After, error messages and spacing of requests."""

from __future__ import annotations

import pytest
import requests

from pse_opendata._http import HttpClient
from pse_opendata.exceptions import PseApiError

from conftest import FakeResponse, FakeSession

BAD_SELECT = {"error": {"code": "BadRequest", "message": "Invalid field to be returned requested: nonexistent",
                        "status": 400}}   # recorded answer of the reports API


def sequence(*responses):
    items = list(responses)

    def handler(url, params):
        return items.pop(0)
    return handler


def make(handler, **kwargs):
    slept: list[float] = []
    http = HttpClient(FakeSession(handler), sleep=slept.append, **kwargs)
    return http, slept


def test_retries_server_errors_with_exponential_backoff():
    http, slept = make(sequence(FakeResponse(503), FakeResponse(500), FakeResponse(payload={"value": []})))
    assert http.get("https://x", decode=lambda r: r.json()) == {"value": []}
    assert slept == [2.0, 4.0]


def test_honours_retry_after_on_429():
    http, slept = make(sequence(FakeResponse(429, headers={"Retry-After": "7"}), FakeResponse(payload={})))
    http.get("https://x")
    assert slept == [7.0]


def test_backoff_is_capped():
    http, slept = make(lambda u, p: FakeResponse(503), retries=3, backoff=50.0, max_backoff=60.0)
    with pytest.raises(PseApiError) as err:
        http.get("https://x")
    assert slept == [50.0, 60.0, 60.0]
    assert err.value.status == 503


def test_client_errors_are_not_retried_and_carry_the_api_message():
    http, slept = make(lambda u, p: FakeResponse(400, payload=BAD_SELECT))
    with pytest.raises(PseApiError) as err:
        http.get("https://api.raporty.pse.pl/api/rce-pln")
    assert slept == []
    assert err.value.status == 400 and err.value.code == "BadRequest"
    assert "Invalid field to be returned requested: nonexistent" in str(err.value)


def test_network_errors_are_retried_then_reported():
    http, slept = make(lambda u, p: requests.ConnectionError("connection reset"), retries=2)
    with pytest.raises(PseApiError) as err:
        http.get("https://x")
    assert err.value.status is None
    assert len(slept) == 2


def test_truncated_json_is_retried():
    http, _ = make(sequence(FakeResponse(content=b'{"value": ['), FakeResponse(payload={"value": [1]})))
    assert http.get("https://x", decode=lambda r: r.json()) == {"value": [1]}


def test_min_interval_spaces_requests():
    now = [100.0]
    slept: list[float] = []

    def sleep(s: float) -> None:
        slept.append(s)
        now[0] += s

    http = HttpClient(FakeSession(lambda u, p: FakeResponse(payload={})), min_interval=15.0, sleep=sleep,
                      clock=lambda: now[0])
    http.get("https://x")
    now[0] += 5.0
    http.get("https://x")
    assert slept == [10.0]


def test_user_agent_names_the_package():
    seen = {}

    class Session(FakeSession):
        def get(self, url, params=None, timeout=None, headers=None):
            seen.update(headers or {})
            return FakeResponse(payload={})

    HttpClient(Session(None)).get("https://x")
    assert seen["User-Agent"].startswith("pse-opendata/")

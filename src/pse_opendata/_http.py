"""HTTP with retries, exponential backoff and a minimum pause between requests."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any, TypeVar

import requests

from pse_opendata._version import __version__
from pse_opendata.exceptions import PseApiError, PseError

log = logging.getLogger("pse_opendata")

USER_AGENT = f"pse-opendata/{__version__} (+https://github.com/kwwaleszczynski-del/pse-opendata)"
# network failures worth another attempt; other RequestException subclasses (bad URL, ...) are raised at once
RETRY_ERRORS = (requests.ConnectionError, requests.Timeout, requests.exceptions.ChunkedEncodingError,
                requests.exceptions.ContentDecodingError)
T = TypeVar("T")


def _retry_after(response: requests.Response) -> float | None:
    value = response.headers.get("Retry-After")
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None


def _error_message(response: requests.Response) -> tuple[str, str | None]:
    """Message and code of an error response; the reports API answers ``{"error": {"code", "message"}}``."""
    try:
        err = response.json().get("error", {})
        return str(err.get("message") or response.reason), err.get("code")
    except (ValueError, AttributeError):
        return f"{response.reason or 'HTTP error'}", None


class HttpClient:
    """GET requests with retries on network errors (also a connection dropped mid-body), HTTP 429 and 5xx.

    Waits ``backoff * 2**attempt`` seconds (at most ``max_backoff``) between attempts, or what ``Retry-After`` asks
    for. ``min_interval`` is the pause between the end of one request and the start of the next one.
    ``sleep`` and ``clock`` can be replaced in tests.
    """

    def __init__(
        self,
        session: requests.Session | None = None,
        *,
        timeout: float = 60.0,
        retries: int = 4,
        backoff: float = 2.0,
        max_backoff: float = 120.0,
        min_interval: float = 0.0,
        user_agent: str = USER_AGENT,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.session = session if session is not None else requests.Session()
        self.timeout = timeout
        self.retries = retries
        self.backoff = backoff
        self.max_backoff = max_backoff
        self.min_interval = min_interval
        self.user_agent = user_agent
        self._sleep = sleep
        self._clock = clock
        self._last_done: float | None = None

    def _wait_for_slot(self) -> None:
        if self._last_done is None or self.min_interval <= 0:
            return
        wait = self._last_done + self.min_interval - self._clock()
        if wait > 0:
            self._sleep(wait)

    def _delay(self, attempt: int, response: requests.Response | None) -> float:
        hinted = _retry_after(response) if response is not None else None
        if hinted is not None:
            return min(hinted, self.max_backoff)
        return min(self.backoff * 2**attempt, self.max_backoff)

    def get(self, url: str, params: dict[str, Any] | None = None,
            decode: Callable[[requests.Response], T] | None = None) -> Any:
        """GET ``url`` and return ``decode(response)`` (the response itself without ``decode``).

        A plain ``ValueError`` from ``decode`` (e.g. truncated JSON) is retried like a network error; errors of
        this package raised by ``decode`` are not. Raises :class:`PseApiError` when the request finally fails or the
        server answers a non-retryable error.
        """
        last_error: PseApiError | None = None
        for attempt in range(self.retries + 1):
            self._wait_for_slot()
            response = None
            try:
                response = self.session.get(url, params=params, timeout=self.timeout,
                                            headers={"User-Agent": self.user_agent})
            except RETRY_ERRORS as e:
                last_error = PseApiError(f"request failed: {e}", url=url)
            except requests.RequestException as e:
                raise PseApiError(f"request failed: {e}", url=url) from e
            finally:
                self._last_done = self._clock()
            if response is not None:
                status = response.status_code
                if status >= 400:
                    message, code = _error_message(response)
                    last_error = PseApiError(f"HTTP {status} from {url}: {message}", status=status, code=code, url=url)
                    if status != 429 and status < 500:
                        raise last_error
                else:
                    try:
                        return decode(response) if decode is not None else response
                    except PseError:
                        raise
                    except ValueError as e:
                        last_error = PseApiError(f"invalid response from {url}: {e}", status=status, url=url)
            if attempt < self.retries:
                delay = self._delay(attempt, response)
                log.warning("%s; retry %d/%d in %.0f s", last_error, attempt + 1, self.retries, delay)
                self._sleep(delay)
        assert last_error is not None
        raise last_error

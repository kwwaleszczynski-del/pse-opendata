"""Exceptions raised by pse-opendata. All of them derive from :class:`PseError`."""

from __future__ import annotations


class PseError(Exception):
    """Base class of every error raised by this package."""


class PseApiError(PseError):
    """An HTTP request to a PSE server failed (after retries, where retrying makes sense).

    Attributes:
        status: HTTP status code, or ``None`` when no response was received (network error, timeout).
        code: error code from the JSON error body of the reports API (e.g. ``"BadRequest"``), if any.
        url: the requested URL.
    """

    def __init__(self, message: str, *, status: int | None = None, code: str | None = None, url: str | None = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.url = url


class UnknownReportError(PseError, LookupError):
    """The report name is not in the catalogue (see :func:`pse_opendata.reports`)."""


class UnknownFieldError(PseError, ValueError):
    """A requested field does not belong to the report."""


class CacheMissError(PseError):
    """Offline mode was requested but a month is not in the cache."""


class LegacyFormatError(PseError, ValueError):
    """The legacy CSV export returned something that is not the expected CSV (e.g. an HTML error page)."""

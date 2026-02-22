"""Custom exceptions for ASP sign retrieval."""

from __future__ import annotations


class SignRetrievalError(Exception):
    """Base exception for all sign retrieval errors."""

    pass


class SODAAPIError(SignRetrievalError):
    """SODA API HTTP error after retries exhausted.

    Raised when the SODA API returns an HTTP error (4xx/5xx) or a
    transport error (connection refused, timeout) and all retry
    attempts have been exhausted.

    Attributes:
        status_code: HTTP status code if available, None for transport errors.
        detail: Human-readable error description.
    """

    def __init__(self, status_code: int | None, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        code_str = str(status_code) if status_code is not None else "N/A"
        super().__init__(f"SODA API error (HTTP {code_str}): {detail}")


class IncompleteResultsError(SignRetrievalError):
    """Pagination interrupted before all records were fetched.

    Raised when a paginated SODA query succeeds for some pages but
    fails on a subsequent page (e.g., rate limiting, connection drop).
    Per user decision: incomplete results are treated as failure.

    Attributes:
        records_fetched: Number of records successfully fetched before failure.
        detail: Human-readable error description.
    """

    def __init__(self, records_fetched: int, detail: str) -> None:
        self.records_fetched = records_fetched
        self.detail = detail
        super().__init__(
            f"Incomplete SODA results ({records_fetched} records fetched): {detail}"
        )

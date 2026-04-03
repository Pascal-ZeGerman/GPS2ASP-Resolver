"""Tests for gps2asp.suspension.poller — NYC 311 API suspension client."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from gps2asp.suspension import SuspensionInfo
from gps2asp.suspension.poller import NYC311Client, NYC311AuthError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_response(status: str, details: str = "", exception_name: str = "") -> dict:
    """Build a 311 API response body with a single ASP item."""
    return {
        "days": [
            {
                "today_id": "20260403",
                "items": [
                    {
                        "type": "Alternate Side Parking",
                        "status": status,
                        "details": details,
                        "exceptionName": exception_name,
                    }
                ],
            }
        ]
    }


def _mock_success_response(body: dict) -> MagicMock:
    """Create a mock httpx.Response for a 200 OK."""
    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status = MagicMock()  # no-op
    resp.json.return_value = body
    return resp


def _mock_http_error_response(status_code: int) -> MagicMock:
    """Create a mock httpx.Response that raises HTTPStatusError on raise_for_status."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        f"HTTP {status_code}",
        request=MagicMock(),
        response=MagicMock(status_code=status_code),
    )
    return resp


# ---------------------------------------------------------------------------
# Test 1: SUSPENDED -> is_suspended=True
# ---------------------------------------------------------------------------


async def test_suspended() -> None:
    """SUSPENDED status returns SuspensionInfo(is_suspended=True, source='emergency')."""
    body = _make_response("SUSPENDED", "Snow Emergency", "Snow Emergency")
    mock_resp = _mock_success_response(body)

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("gps2asp.suspension.poller.httpx.AsyncClient", return_value=mock_client):
        client = NYC311Client(api_key="test-key")
        result = await client.fetch_status()

    assert result == SuspensionInfo(
        is_suspended=True, reason="Snow Emergency", source="emergency"
    )


# ---------------------------------------------------------------------------
# Test 2: IN_EFFECT -> is_suspended=False
# ---------------------------------------------------------------------------


async def test_in_effect() -> None:
    """IN_EFFECT status returns SuspensionInfo(is_suspended=False)."""
    body = _make_response("IN_EFFECT")
    mock_resp = _mock_success_response(body)

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("gps2asp.suspension.poller.httpx.AsyncClient", return_value=mock_client):
        client = NYC311Client(api_key="test-key")
        result = await client.fetch_status()

    assert result == SuspensionInfo(is_suspended=False, reason=None, source="none")


# ---------------------------------------------------------------------------
# Test 3: NOT_IN_EFFECT -> is_suspended=False
# ---------------------------------------------------------------------------


async def test_not_in_effect() -> None:
    """NOT_IN_EFFECT status returns SuspensionInfo(is_suspended=False)."""
    body = _make_response("NOT_IN_EFFECT")
    mock_resp = _mock_success_response(body)

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("gps2asp.suspension.poller.httpx.AsyncClient", return_value=mock_client):
        client = NYC311Client(api_key="test-key")
        result = await client.fetch_status()

    assert result == SuspensionInfo(is_suspended=False, reason=None, source="none")


# ---------------------------------------------------------------------------
# Test 4: NO_INFORMATION -> fail open (is_suspended=False)
# ---------------------------------------------------------------------------


async def test_no_information() -> None:
    """NO_INFORMATION status returns SuspensionInfo(is_suspended=False) — fail open."""
    body = _make_response("NO_INFORMATION")
    mock_resp = _mock_success_response(body)

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("gps2asp.suspension.poller.httpx.AsyncClient", return_value=mock_client):
        client = NYC311Client(api_key="test-key")
        result = await client.fetch_status()

    assert result == SuspensionInfo(is_suspended=False, reason=None, source="none")


# ---------------------------------------------------------------------------
# Test 5: No API key -> immediate fail-open, no HTTP call
# ---------------------------------------------------------------------------


async def test_no_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """No API key returns SuspensionInfo(is_suspended=False) without HTTP call."""
    monkeypatch.delenv("NYC_311_API_KEY", raising=False)

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("gps2asp.suspension.poller.httpx.AsyncClient", return_value=mock_client):
        client = NYC311Client(api_key=None)
        result = await client.fetch_status()

    assert result == SuspensionInfo(is_suspended=False, reason=None, source="none")
    mock_client.get.assert_not_called()


# ---------------------------------------------------------------------------
# Test 6: Env var fallback -> reads NYC_311_API_KEY, sends auth header
# ---------------------------------------------------------------------------


async def test_env_var_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """NYC_311_API_KEY env var is used when api_key arg is None."""
    monkeypatch.setenv("NYC_311_API_KEY", "env-test-key")

    body = _make_response("IN_EFFECT")
    mock_resp = _mock_success_response(body)

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("gps2asp.suspension.poller.httpx.AsyncClient", return_value=mock_client):
        client = NYC311Client(api_key=None)
        result = await client.fetch_status()

    # Verify the HTTP call was made (key was resolved from env)
    mock_client.get.assert_called_once()
    call_kwargs = mock_client.get.call_args
    # Check the auth header
    assert call_kwargs.kwargs["headers"]["Ocp-Apim-Subscription-Key"] == "env-test-key"


# ---------------------------------------------------------------------------
# Test 7: HTTP 401 -> raises NYC311AuthError
# ---------------------------------------------------------------------------


async def test_auth_error_401() -> None:
    """HTTP 401 raises NYC311AuthError."""
    mock_resp = _mock_http_error_response(401)

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("gps2asp.suspension.poller.httpx.AsyncClient", return_value=mock_client):
        client = NYC311Client(api_key="bad-key")
        with pytest.raises(NYC311AuthError):
            await client.fetch_status()


# ---------------------------------------------------------------------------
# Test 8: HTTP 403 -> raises NYC311AuthError
# ---------------------------------------------------------------------------


async def test_auth_error_403() -> None:
    """HTTP 403 raises NYC311AuthError."""
    mock_resp = _mock_http_error_response(403)

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("gps2asp.suspension.poller.httpx.AsyncClient", return_value=mock_client):
        client = NYC311Client(api_key="bad-key")
        with pytest.raises(NYC311AuthError):
            await client.fetch_status()


# ---------------------------------------------------------------------------
# Test 9: Network error -> fail open
# ---------------------------------------------------------------------------


async def test_network_error_fail_open() -> None:
    """httpx.ConnectError returns fail-open SuspensionInfo, does NOT raise."""
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("gps2asp.suspension.poller.httpx.AsyncClient", return_value=mock_client):
        with patch("gps2asp.suspension.poller.asyncio.sleep", new_callable=AsyncMock):
            client = NYC311Client(api_key="test-key")
            result = await client.fetch_status()

    assert result == SuspensionInfo(is_suspended=False, reason=None, source="none")


# ---------------------------------------------------------------------------
# Test 10: Retry succeeds on 3rd attempt
# ---------------------------------------------------------------------------


async def test_retry_succeeds_on_third_attempt() -> None:
    """First 2 calls fail with ConnectError, 3rd succeeds with SUSPENDED."""
    body = _make_response("SUSPENDED", "Snow Emergency", "Snow Emergency")
    mock_resp = _mock_success_response(body)

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(
        side_effect=[
            httpx.ConnectError("fail 1"),
            httpx.ConnectError("fail 2"),
            mock_resp,
        ]
    )
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("gps2asp.suspension.poller.httpx.AsyncClient", return_value=mock_client):
        with patch("gps2asp.suspension.poller.asyncio.sleep", new_callable=AsyncMock):
            client = NYC311Client(api_key="test-key")
            result = await client.fetch_status()

    assert result == SuspensionInfo(
        is_suspended=True, reason="Snow Emergency", source="emergency"
    )
    assert mock_client.get.call_count == 3


# ---------------------------------------------------------------------------
# Test 11: All retries exhausted -> fail open
# ---------------------------------------------------------------------------


async def test_retries_exhausted_fail_open() -> None:
    """All 3 attempts fail with ConnectError -> fail-open SuspensionInfo."""
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(
        side_effect=[
            httpx.ConnectError("fail 1"),
            httpx.ConnectError("fail 2"),
            httpx.ConnectError("fail 3"),
        ]
    )
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("gps2asp.suspension.poller.httpx.AsyncClient", return_value=mock_client):
        with patch("gps2asp.suspension.poller.asyncio.sleep", new_callable=AsyncMock):
            client = NYC311Client(api_key="test-key")
            result = await client.fetch_status()

    assert result == SuspensionInfo(is_suspended=False, reason=None, source="none")
    assert mock_client.get.call_count == 3


# ---------------------------------------------------------------------------
# Test 12: Non-ASP item filtered out
# ---------------------------------------------------------------------------


async def test_non_asp_item_filtered() -> None:
    """Items with type != 'Alternate Side Parking' are ignored."""
    body = {
        "days": [
            {
                "today_id": "20260403",
                "items": [
                    {
                        "type": "Street Cleaning",
                        "status": "SUSPENDED",
                        "details": "Snow Emergency",
                        "exceptionName": "Snow Emergency",
                    }
                ],
            }
        ]
    }
    mock_resp = _mock_success_response(body)

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("gps2asp.suspension.poller.httpx.AsyncClient", return_value=mock_client):
        client = NYC311Client(api_key="test-key")
        result = await client.fetch_status()

    assert result == SuspensionInfo(is_suspended=False, reason=None, source="none")


# ---------------------------------------------------------------------------
# Test 13: Empty days array
# ---------------------------------------------------------------------------


async def test_empty_days() -> None:
    """Response with empty days array returns fail-open SuspensionInfo."""
    body = {"days": []}
    mock_resp = _mock_success_response(body)

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("gps2asp.suspension.poller.httpx.AsyncClient", return_value=mock_client):
        client = NYC311Client(api_key="test-key")
        result = await client.fetch_status()

    assert result == SuspensionInfo(is_suspended=False, reason=None, source="none")

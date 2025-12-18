"""Integration tests for the full unlock flow."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from truenas_unlock import Config, Dataset, run_unlock


@pytest.fixture
def mock_config() -> Config:
    """Return a mock configuration with multiple datasets."""
    return Config(
        host="truenas.local",
        api_key="secret",
        datasets=[
            Dataset(path="tank/secure", secret="pass1"),
            Dataset(path="tank/media", secret="pass2"),
        ],
    )


@pytest.mark.anyio
async def test_integration_run_unlock_success(mock_config: Config) -> None:
    """Test that run_unlock returns True when all datasets are successfully checked/unlocked.

    Scenario:
    - tank/secure is LOCKED -> Unlocked successfully.
    - tank/media is UNLOCKED -> Skipped.
    """
    mock_response_version = MagicMock(spec=httpx.Response)
    mock_response_version.status_code = 200
    mock_response_version.json.return_value = "TrueNAS-25.04.0"

    mock_response_locked = MagicMock(spec=httpx.Response)
    mock_response_locked.status_code = 200
    mock_response_locked.json.return_value = [{"locked": True}]

    mock_response_unlocked = MagicMock(spec=httpx.Response)
    mock_response_unlocked.status_code = 200
    mock_response_unlocked.json.return_value = [{"locked": False}]

    mock_response_success = MagicMock(spec=httpx.Response)
    mock_response_success.status_code = 200
    mock_response_success.json.return_value = {}

    # We need to simulate the sequence of calls:
    # 1. GET system/version -> "TrueNAS-25.04.0"
    # 2. GET is_locked(tank/secure) -> True
    # 3. POST unlock(tank/secure) -> Success
    # 4. GET is_locked(tank/media) -> False

    # We'll use a side_effect function to return the right response based on URL/method
    async def request_handler(method: str, url: str, **kwargs: object) -> MagicMock:  # noqa: ARG001
        if "system/version" in url and method == "GET":
            return mock_response_version
        if "tank/secure" in url and method == "GET":
            return mock_response_locked
        if "unlock" in url and method == "POST":
            return mock_response_success
        if "tank/media" in url and method == "GET":
            return mock_response_unlocked
        return MagicMock(status_code=404)

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.request.side_effect = request_handler
        mock_client_cls.return_value = mock_client
        mock_client.__aenter__.return_value = mock_client

        result = await run_unlock(mock_config)

        assert result is True
        assert mock_client.request.call_count == 4  # noqa: PLR2004


@pytest.mark.anyio
async def test_integration_run_unlock_partial_failure(mock_config: Config) -> None:
    """Test that run_unlock returns False if ANY dataset check fails.

    This validates the 'Panic Mode' trigger logic.





    Scenario:


    - tank/secure -> HTTP 500 Error (TrueNAS API glitch)


    - tank/media -> Unlocked


    """
    mock_response_error = MagicMock(spec=httpx.Response)

    mock_response_error.status_code = 500

    mock_response_error.text = "Internal Server Error"

    mock_response_unlocked = MagicMock(spec=httpx.Response)

    mock_response_unlocked.status_code = 200

    mock_response_unlocked.json.return_value = [{"locked": False}]

    async def request_handler(method: str, url: str, **kwargs: object) -> MagicMock:  # noqa: ARG001
        if "tank/secure" in url:
            return mock_response_error

        if "tank/media" in url:
            return mock_response_unlocked

        return MagicMock(status_code=404)

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.request.side_effect = request_handler
        mock_client_cls.return_value = mock_client
        mock_client.__aenter__.return_value = mock_client

        result = await run_unlock(mock_config)

        # Should return False because one failed
        assert result is False


@pytest.mark.anyio
async def test_integration_run_unlock_connection_refused(mock_config: Config) -> None:
    """Test that run_unlock returns False when TrueNAS is offline.

    Scenario:
    - ConnectionRefusedError on all requests
    """
    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.request.side_effect = httpx.ConnectError("Connection refused")
        mock_client_cls.return_value = mock_client
        mock_client.__aenter__.return_value = mock_client

        result = await run_unlock(mock_config)

        assert result is False

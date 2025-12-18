"""Tests for TrueNasClient."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from truenas_unlock import Config, Dataset, SecretsMode, TrueNasClient


@pytest.fixture
def mock_config() -> Config:
    """Return a mock configuration."""
    return Config(
        host="truenas.local",
        api_key="secret-key",
        secrets=SecretsMode.INLINE,
        datasets=[
            Dataset(path="tank/secure", secret="pass1"),
        ],
    )


@pytest.fixture
def mock_httpx_client() -> MagicMock:
    """Return a mock httpx client."""
    client = MagicMock(spec=httpx.AsyncClient)
    client.request = AsyncMock()
    client.aclose = AsyncMock()
    return client


@pytest.mark.anyio
async def test_client_context_manager(mock_config: Config) -> None:
    """Test TrueNasClient context manager."""
    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_instance = AsyncMock()
        mock_client_cls.return_value = mock_instance

        async with TrueNasClient(mock_config) as client:
            assert client.client is mock_instance

        mock_instance.aclose.assert_called_once()


@pytest.mark.anyio
async def test_request_success(mock_config: Config, mock_httpx_client: MagicMock) -> None:
    """Test _request handles 200 OK correctly."""
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_httpx_client.request.return_value = mock_response

    async with TrueNasClient(mock_config) as client:
        client._client = mock_httpx_client  # Inject mock  # noqa: SLF001
        response = await client._request("GET", "test")  # noqa: SLF001

        assert response is mock_response
    mock_httpx_client.request.assert_called_once()


@pytest.mark.anyio
async def test_request_failure(mock_config: Config, mock_httpx_client: MagicMock) -> None:
    """Test _request handles errors correctly."""
    # Case 1: 404 Error
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 404
    mock_response.text = "Not Found"
    mock_httpx_client.request.return_value = mock_response

    async with TrueNasClient(mock_config) as client:
        client._client = mock_httpx_client  # noqa: SLF001
        response = await client._request("GET", "test")  # noqa: SLF001
        assert response is None

    # Case 2: Exception
    mock_httpx_client.request.side_effect = httpx.RequestError("Connection failed")

    async with TrueNasClient(mock_config) as client:
        client._client = mock_httpx_client  # noqa: SLF001
        response = await client._request("GET", "test")  # noqa: SLF001
        assert response is None


@pytest.mark.anyio
async def test_is_locked(mock_config: Config, mock_httpx_client: MagicMock) -> None:
    """Test is_locked logic."""
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_httpx_client.request.return_value = mock_response

    async with TrueNasClient(mock_config) as client:
        client._client = mock_httpx_client  # noqa: SLF001
        ds = mock_config.datasets[0]

        # Case 1: Locked
        mock_response.json.return_value = [{"locked": True}]
        assert await client.is_locked(ds) is True

        # Case 2: Unlocked
        mock_response.json.return_value = [{"locked": False}]
        assert await client.is_locked(ds) is False

        # Case 3: Invalid response
        mock_response.json.side_effect = ValueError
        assert await client.is_locked(ds) is None


@pytest.fixture
def mock_config_with_version() -> Config:
    """Return a mock configuration with version specified."""
    return Config(
        host="truenas.local",
        api_key="secret-key",
        secrets=SecretsMode.INLINE,
        truenas_version="25.04",  # New version, uses "options"
        datasets=[
            Dataset(path="tank/secure", secret="pass1"),
        ],
    )


@pytest.mark.anyio
async def test_unlock(
    mock_config_with_version: Config,
    mock_httpx_client: MagicMock,
) -> None:
    """Test unlock logic."""
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_httpx_client.request.return_value = mock_response

    async with TrueNasClient(mock_config_with_version) as client:
        client._client = mock_httpx_client  # noqa: SLF001
        ds = mock_config_with_version.datasets[0]

        assert await client.unlock(ds) is True

        mock_httpx_client.request.assert_called_with(
            "POST",
            "https://truenas.local/api/v2.0/pool/dataset/unlock",
            headers={"Authorization": "Bearer secret-key"},
            json={
                "id": "tank/secure",
                "options": {
                    "key_file": False,
                    "recursive": False,
                    "force": True,
                    "toggle_attachments": True,
                    "datasets": [{"name": "tank/secure", "passphrase": "pass1"}],
                },
            },
        )


@pytest.mark.anyio
async def test_lock(mock_config: Config, mock_httpx_client: MagicMock) -> None:
    """Test lock logic."""
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_httpx_client.request.return_value = mock_response

    async with TrueNasClient(mock_config) as client:
        client._client = mock_httpx_client  # noqa: SLF001
        ds = mock_config.datasets[0]

        assert await client.lock(ds, force=True) is True

        mock_httpx_client.request.assert_called_with(
            "POST",
            "https://truenas.local/api/v2.0/pool/dataset/lock",
            headers={"Authorization": "Bearer secret-key"},
            json={
                "id": "tank/secure",
                "options": {
                    "force_umount": True,
                },
            },
        )

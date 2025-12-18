"""Tests for TrueNAS version detection and API compatibility."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from truenas_unlock import (
    Config,
    Dataset,
    SecretsMode,
    TrueNasClient,
    _parse_truenas_version,
    _uses_new_unlock_api,
)


class TestParseVersion:
    """Tests for _parse_truenas_version function."""

    def test_new_format(self) -> None:
        """Test parsing new format: TrueNAS-25.04.0."""
        assert _parse_truenas_version("TrueNAS-25.04.0") == (25, 4)

    def test_old_format(self) -> None:
        """Test parsing old format: TrueNAS-SCALE-24.10.2.1."""
        assert _parse_truenas_version("TrueNAS-SCALE-24.10.2.1") == (24, 10)

    def test_simple_version(self) -> None:
        """Test parsing simple version string."""
        assert _parse_truenas_version("25.04") == (25, 4)
        assert _parse_truenas_version("24.10.2") == (24, 10)

    def test_invalid_version(self) -> None:
        """Test parsing invalid version string."""
        assert _parse_truenas_version("invalid") is None
        assert _parse_truenas_version("") is None

    def test_edge_cases(self) -> None:
        """Test edge cases."""
        assert _parse_truenas_version("25.04.2.6") == (25, 4)
        assert _parse_truenas_version("1.0") == (1, 0)


class TestUsesNewUnlockApi:
    """Tests for _uses_new_unlock_api function."""

    def test_new_api_versions(self) -> None:
        """Test versions that should use new API (>= 25.04)."""
        assert _uses_new_unlock_api((25, 4)) is True
        assert _uses_new_unlock_api((25, 10)) is True
        assert _uses_new_unlock_api((26, 0)) is True

    def test_old_api_versions(self) -> None:
        """Test versions that should use old API (< 25.04)."""
        assert _uses_new_unlock_api((24, 10)) is False
        assert _uses_new_unlock_api((24, 4)) is False
        assert _uses_new_unlock_api((25, 3)) is False

    def test_none_defaults_to_new(self) -> None:
        """Test that None version defaults to new API."""
        assert _uses_new_unlock_api(None) is True


class TestClientVersionDetection:
    """Tests for TrueNasClient version detection."""

    @pytest.fixture
    def mock_config_no_version(self) -> Config:
        """Return a mock config without truenas_version."""
        return Config(
            host="truenas.local",
            api_key="secret-key",
            secrets=SecretsMode.INLINE,
            datasets=[Dataset(path="tank/secure", secret="pass1")],
        )

    @pytest.fixture
    def mock_config_with_version(self) -> Config:
        """Return a mock config with truenas_version."""
        return Config(
            host="truenas.local",
            api_key="secret-key",
            secrets=SecretsMode.INLINE,
            truenas_version="24.10",  # Old version
            datasets=[Dataset(path="tank/secure", secret="pass1")],
        )

    @pytest.mark.anyio
    async def test_uses_config_version_when_provided(
        self, mock_config_with_version: Config,
    ) -> None:
        """Test that config version is used when provided, skipping API call."""
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value = mock_client
            mock_client.__aenter__.return_value = mock_client

            async with TrueNasClient(mock_config_with_version) as client:
                use_new = await client._get_use_new_api()  # noqa: SLF001

                # Should use old API (24.10 < 25.04)
                assert use_new is False
                # Should NOT have made a version API call
                version_calls = [
                    call
                    for call in mock_client.request.call_args_list
                    if "system/version" in str(call)
                ]
                assert len(version_calls) == 0

    @pytest.mark.anyio
    async def test_fetches_version_when_not_in_config(
        self, mock_config_no_version: Config,
    ) -> None:
        """Test that version is fetched from API when not in config."""
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = "TrueNAS-25.04.0"

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.request.return_value = mock_response
            mock_client_cls.return_value = mock_client
            mock_client.__aenter__.return_value = mock_client

            async with TrueNasClient(mock_config_no_version) as client:
                use_new = await client._get_use_new_api()  # noqa: SLF001

                # Should use new API (25.04 >= 25.04)
                assert use_new is True

    @pytest.mark.anyio
    async def test_caches_api_detection(self, mock_config_no_version: Config) -> None:
        """Test that API style is cached after first detection."""
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = "TrueNAS-25.04.0"

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.request.return_value = mock_response
            mock_client_cls.return_value = mock_client
            mock_client.__aenter__.return_value = mock_client

            async with TrueNasClient(mock_config_no_version) as client:
                # First call
                await client._get_use_new_api()  # noqa: SLF001
                first_call_count = mock_client.request.call_count

                # Second call should use cached value
                await client._get_use_new_api()  # noqa: SLF001
                assert mock_client.request.call_count == first_call_count

    @pytest.mark.anyio
    async def test_unlock_uses_old_api_param(
        self, mock_config_with_version: Config,
    ) -> None:
        """Test that unlock uses unlock_options for old TrueNAS versions."""
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.request.return_value = mock_response
            mock_client_cls.return_value = mock_client
            mock_client.__aenter__.return_value = mock_client

            async with TrueNasClient(mock_config_with_version) as client:
                ds = mock_config_with_version.datasets[0]
                await client.unlock(ds)

                # Check the unlock call used unlock_options
                unlock_call = next(
                    call
                    for call in mock_client.request.call_args_list
                    if "unlock" in str(call)
                )
                json_arg = unlock_call.kwargs.get("json", {})
                assert "unlock_options" in json_arg
                assert "options" not in json_arg

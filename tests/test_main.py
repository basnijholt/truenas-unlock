"""Tests for main CLI functions."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from truenas_unlock import Config, Dataset, app, run_lock, run_status, run_unlock

runner = CliRunner()


@pytest.fixture
def mock_config() -> Config:
    """Return a mock configuration."""
    return Config(
        host="truenas.local",
        api_key="secret",
        datasets=[Dataset(path="tank/secure", secret="pass")],
    )


@pytest.fixture
def mock_client_cls() -> MagicMock:
    """Mock TrueNasClient class."""
    with patch("truenas_unlock.TrueNasClient") as mock_cls:
        mock_instance = AsyncMock()
        mock_instance.__aenter__.return_value = mock_instance  # Fix: context manager returns itself
        mock_cls.return_value = mock_instance
        yield mock_cls


@pytest.mark.anyio
async def test_run_unlock_success(mock_config: Config, mock_client_cls: MagicMock) -> None:
    """Test run_unlock returns True on success."""
    mock_instance = mock_client_cls.return_value
    mock_instance.check_and_unlock.return_value = True  # Unlocked successfully

    result = await run_unlock(mock_config)
    assert result is True
    mock_instance.check_and_unlock.assert_called_once()


@pytest.mark.anyio
async def test_run_unlock_connection_error(mock_config: Config, mock_client_cls: MagicMock) -> None:
    """Test run_unlock returns False on connection error."""
    mock_instance = mock_client_cls.return_value
    mock_instance.check_and_unlock.side_effect = ConnectionError("Fail")

    result = await run_unlock(mock_config)
    assert result is False


@pytest.mark.anyio
async def test_run_unlock_exception(mock_config: Config, mock_client_cls: MagicMock) -> None:
    """Test run_unlock returns False on unexpected exception."""
    mock_instance = mock_client_cls.return_value
    mock_instance.check_and_unlock.side_effect = ValueError("Boom")

    result = await run_unlock(mock_config)
    assert result is False


@pytest.mark.anyio
async def test_run_lock(mock_config: Config, mock_client_cls: MagicMock) -> None:
    """Test run_lock logic."""
    mock_instance = mock_client_cls.return_value
    mock_instance.is_locked.return_value = False  # Currently unlocked

    await run_lock(mock_config, force=True)

    mock_instance.lock.assert_called_once_with(mock_config.datasets[0], force=True)


@pytest.mark.anyio
async def test_run_status(mock_config: Config, mock_client_cls: MagicMock) -> None:
    """Test run_status logic."""
    mock_instance = mock_client_cls.return_value
    mock_instance.is_locked.return_value = True

    await run_status(mock_config)

    mock_instance.is_locked.assert_called_once()


def test_cli_help() -> None:
    """Test CLI help command."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "Unlock TrueNAS ZFS datasets" in result.stdout


def test_cli_missing_config(tmp_path: object) -> None:  # noqa: ARG001
    """Test CLI fails without config."""
    # Ensure no config exists in default paths
    with patch("truenas_unlock.find_config", return_value=None):
        result = runner.invoke(app)
        assert result.exit_code == 1
        assert "Config not found" in result.stderr


def test_cli_with_config(tmp_path: object, mock_client_cls: object) -> None:  # noqa: ARG001
    """Test CLI runs with config file."""
    config_file = tmp_path / "config.yaml"
    config_file.write_text("host: test\napi_key: key\ndatasets:\n  tank/ds: pass")

    # Mock run_unlock to be awaitable
    with patch("truenas_unlock.run_unlock", new_callable=AsyncMock) as mock_run:
        result = runner.invoke(app, ["--config", str(config_file)])
        assert result.exit_code == 0
        mock_run.assert_called_once()


def test_cli_daemon_mode(tmp_path: object, mock_client_cls: object) -> None:  # noqa: ARG001
    """Test CLI daemon mode loop."""
    config_file = tmp_path / "config.yaml"
    config_file.write_text("host: test\napi_key: key\ndatasets:\n  tank/ds: pass")

    # Mock asyncio.run to return: True (success), False (failure), then raise KeyboardInterrupt to exit
    with patch("asyncio.run") as mock_run, patch("time.sleep") as mock_sleep:
        mock_run.side_effect = [True, False, KeyboardInterrupt]

        result = runner.invoke(app, ["--config", str(config_file), "--daemon", "--interval", "10"])

        assert result.exit_code == 0
        assert mock_run.call_count == 3  # noqa: PLR2004
        # First sleep: success -> 10s
        # Second sleep: failure -> 1s
        mock_sleep.assert_any_call(10)
        mock_sleep.assert_any_call(1)

"""Tests for configuration parsing."""

from pathlib import Path
from textwrap import dedent

import pytest

from truenas_zfs_unlock import Config, Dataset, SecretsMode, resolve_secret


class TestResolveSecret:
    """Tests for resolve_secret function."""

    def test_inline_mode_returns_literal(self, tmp_path: Path) -> None:
        """Inline mode always returns the literal value."""
        secret_file = tmp_path / "secret"
        secret_file.write_text("file-content")

        # Even if file exists, inline mode returns literal
        assert resolve_secret(str(secret_file), SecretsMode.inline) == str(secret_file)
        assert resolve_secret("literal-value", SecretsMode.inline) == "literal-value"

    def test_files_mode_reads_file(self, tmp_path: Path) -> None:
        """Files mode always reads from file."""
        secret_file = tmp_path / "secret"
        secret_file.write_text("file-content\n")

        assert resolve_secret(str(secret_file), SecretsMode.files) == "file-content"

    def test_files_mode_raises_on_missing(self, tmp_path: Path) -> None:
        """Files mode raises error if file doesn't exist."""
        with pytest.raises(FileNotFoundError):
            resolve_secret("/nonexistent/path", SecretsMode.files)

    def test_auto_mode_reads_existing_file(self, tmp_path: Path) -> None:
        """Auto mode reads from file if it exists."""
        secret_file = tmp_path / "secret"
        secret_file.write_text("file-content\n")

        assert resolve_secret(str(secret_file), SecretsMode.auto) == "file-content"

    def test_auto_mode_returns_literal_if_no_file(self) -> None:
        """Auto mode returns literal if file doesn't exist."""
        assert resolve_secret("my-passphrase", SecretsMode.auto) == "my-passphrase"

    def test_auto_mode_expands_tilde(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Auto mode expands ~ in paths."""
        monkeypatch.setenv("HOME", str(tmp_path))
        secret_file = tmp_path / "secret"
        secret_file.write_text("home-secret\n")

        assert resolve_secret("~/secret", SecretsMode.auto) == "home-secret"


class TestDataset:
    """Tests for Dataset model."""

    def test_path_parsing(self) -> None:
        """Test Dataset path parsing."""
        ds = Dataset(path="tank/photos", secret="passphrase")
        assert ds.pool == "tank"
        assert ds.name == "photos"
        assert ds.path == "tank/photos"

    def test_nested_path(self) -> None:
        """Test Dataset with nested path."""
        ds = Dataset(path="tank/data/photos", secret="passphrase")
        assert ds.pool == "tank"
        assert ds.name == "data/photos"

    def test_get_passphrase_inline(self) -> None:
        """Test getting passphrase in inline mode."""
        ds = Dataset(path="tank/photos", secret="my-secret")
        assert ds.get_passphrase(SecretsMode.inline) == "my-secret"

    def test_get_passphrase_from_file(self, tmp_path: Path) -> None:
        """Test getting passphrase from file."""
        key_file = tmp_path / "key"
        key_file.write_text("file-passphrase\n")

        ds = Dataset(path="tank/photos", secret=str(key_file))
        assert ds.get_passphrase(SecretsMode.files) == "file-passphrase"


class TestConfig:
    """Tests for Config model."""

    def test_from_yaml_with_inline_secrets(self, tmp_path: Path) -> None:
        """Test Config loading with inline secrets."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            dedent("""\
            host: 192.168.1.1:443
            api_key: my-api-key
            secrets: inline
            datasets:
              tank/photos: my-passphrase
            """)
        )

        config = Config.from_yaml(config_file)

        assert config.host == "192.168.1.1:443"
        assert config.secrets == SecretsMode.inline
        assert config.get_api_key() == "my-api-key"
        assert len(config.datasets) == 1
        assert config.datasets[0].get_passphrase(config.secrets) == "my-passphrase"

    def test_from_yaml_with_file_secrets(self, tmp_path: Path) -> None:
        """Test Config loading with file-based secrets."""
        config_file = tmp_path / "config.yaml"
        api_key_file = tmp_path / "api-key"
        ds_key_file = tmp_path / "ds-key"

        api_key_file.write_text("test-api-key\n")
        ds_key_file.write_text("test-passphrase\n")

        config_file.write_text(
            dedent(f"""\
            host: 192.168.1.1:443
            api_key: {api_key_file}
            secrets: files
            datasets:
              tank/photos: {ds_key_file}
            """)
        )

        config = Config.from_yaml(config_file)

        assert config.get_api_key() == "test-api-key"
        assert config.datasets[0].get_passphrase(config.secrets) == "test-passphrase"

    def test_from_yaml_auto_mode(self, tmp_path: Path) -> None:
        """Test Config with auto mode (default)."""
        config_file = tmp_path / "config.yaml"
        api_key_file = tmp_path / "api-key"

        api_key_file.write_text("file-api-key\n")

        config_file.write_text(
            dedent(f"""\
            host: 192.168.1.1:443
            api_key: {api_key_file}
            datasets:
              tank/photos: literal-passphrase
            """)
        )

        config = Config.from_yaml(config_file)

        assert config.secrets == SecretsMode.auto
        assert config.get_api_key() == "file-api-key"  # file exists
        assert config.datasets[0].get_passphrase(config.secrets) == "literal-passphrase"  # no file

    def test_legacy_api_key_file_field(self, tmp_path: Path) -> None:
        """Test backwards compatibility with api_key_file field."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            dedent("""\
            host: 192.168.1.1:443
            api_key_file: my-api-key
            secrets: inline
            datasets:
              tank/photos: passphrase
            """)
        )

        config = Config.from_yaml(config_file)
        assert config.get_api_key() == "my-api-key"

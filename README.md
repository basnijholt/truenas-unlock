# TrueNAS ZFS Unlock

[![PyPI](https://img.shields.io/pypi/v/truenas-zfs-unlock)](https://pypi.org/project/truenas-zfs-unlock/)
[![Python](https://img.shields.io/pypi/pyversions/truenas-zfs-unlock)](https://pypi.org/project/truenas-zfs-unlock/)
[![Tests](https://github.com/basnijholt/truenas-zfs-unlock/actions/workflows/test.yml/badge.svg)](https://github.com/basnijholt/truenas-zfs-unlock/actions/workflows/test.yml)
[![License](https://img.shields.io/github/license/basnijholt/truenas-zfs-unlock)](LICENSE)

Unlock encrypted ZFS datasets on TrueNAS via the API.

## Install

```bash
# With uv (recommended)
uv tool install truenas-zfs-unlock

# With pip
pip install truenas-zfs-unlock
```

## Setup

Create `~/.config/truenas-unlock/config.yaml`:

```yaml
host: 192.168.1.214:443
api_key: ~/.secrets/truenas-api-key  # file path or literal
skip_cert_verify: true

# secrets: auto  # auto (default) | files | inline

datasets:
  tank/syncthing: ~/.secrets/syncthing-key  # reads from file
  tank/photos: my-literal-passphrase        # used as-is (no such file)
```

The `secrets` mode controls how values are interpreted:
- **auto** (default): if file exists, read from it; otherwise use as literal
- **files**: always treat values as file paths
- **inline**: always treat values as literal secrets

## Usage

```bash
# Run once
truenas-zfs-unlock

# Run as daemon (every 10 seconds)
truenas-zfs-unlock --daemon

# Custom interval
truenas-zfs-unlock --daemon --interval 30

# Dry run
truenas-zfs-unlock --dry-run
```

## CLI

```
Usage: truenas-zfs-unlock [OPTIONS]

Options:
  -c, --config PATH    Config file path
  -n, --dry-run        Show what would be done
  -d, --daemon         Run continuously
  -i, --interval INT   Seconds between runs [default: 10]
  --help               Show this message and exit.
```

## Development

```bash
# Clone and install
git clone https://github.com/basnijholt/truenas-zfs-unlock
cd truenas-zfs-unlock
uv sync --dev

# Run tests
uv run pytest

# Run lints
uv run ruff check .
uv run mypy truenas_zfs_unlock.py
```

## Credits

Inspired by [ThorpeJosh/truenas-zfs-unlock](https://github.com/ThorpeJosh/truenas-zfs-unlock).

## License

MIT

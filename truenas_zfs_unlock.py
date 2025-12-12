"""TrueNAS ZFS Dataset Unlock.

Unlocks encrypted ZFS datasets on TrueNAS via the API.
"""

from __future__ import annotations

import time
from enum import Enum
from pathlib import Path
from typing import Annotated

import httpx
import typer
import yaml
from pydantic import BaseModel
from rich.console import Console

console = Console()
err_console = Console(stderr=True)

CONFIG_SEARCH_PATHS = [
    Path("config.yaml"),
    Path("config.yml"),
    Path.home() / ".config" / "truenas-unlock" / "config.yaml",
    Path.home() / ".config" / "truenas-unlock" / "config.yml",
]

EXAMPLE_CONFIG = """\
host: 192.168.1.214:443
api_key: ~/.secrets/truenas-api-key  # file path or literal value
skip_cert_verify: true
# secrets: auto  # auto (default), files, or inline

datasets:
  tank/syncthing: ~/.secrets/syncthing-key
  tank/photos: my-literal-passphrase
"""


class SecretsMode(str, Enum):
    """How to interpret secret values."""

    auto = "auto"  # check if file exists, otherwise use as literal
    files = "files"  # always treat as file paths
    inline = "inline"  # always treat as literal values


def resolve_secret(value: str, mode: SecretsMode) -> str:
    """Resolve a secret value based on the secrets mode."""
    if mode == SecretsMode.inline:
        return value

    path = Path(value).expanduser()

    if mode == SecretsMode.files:
        return path.read_text().strip()

    # auto mode: check if file exists
    if path.exists() and path.is_file():
        return path.read_text().strip()
    return value


class Dataset(BaseModel):
    """A ZFS dataset to unlock."""

    path: str
    secret: str  # file path or literal passphrase

    @property
    def pool(self) -> str:
        return self.path.split("/")[0]

    @property
    def name(self) -> str:
        return "/".join(self.path.split("/")[1:])

    def get_passphrase(self, mode: SecretsMode) -> str:
        return resolve_secret(self.secret, mode)


class Config(BaseModel):
    """Application configuration."""

    host: str
    api_key: str  # file path or literal value
    skip_cert_verify: bool = False
    secrets: SecretsMode = SecretsMode.auto
    datasets: list[Dataset]

    def get_api_key(self) -> str:
        return resolve_secret(self.api_key, self.secrets)

    @classmethod
    def from_yaml(cls, path: Path) -> Config:
        data = yaml.safe_load(path.read_text())

        # Handle legacy api_key_file field
        if "api_key_file" in data and "api_key" not in data:
            data["api_key"] = data.pop("api_key_file")

        # Convert simple dict format to list of Dataset objects
        datasets_raw = data.pop("datasets", {})
        datasets = [Dataset(path=ds_path, secret=secret) for ds_path, secret in datasets_raw.items()]

        return cls(datasets=datasets, **data)


class TrueNasClient:
    """Client for TrueNAS API operations."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.client = httpx.Client(
            timeout=httpx.Timeout(connect=3.0, read=30.0, write=30.0, pool=5.0),
            verify=not config.skip_cert_verify,
        )

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.config.get_api_key()}"}

    @property
    def _base_url(self) -> str:
        return f"https://{self.config.host}/api/v2.0"

    def is_locked(self, dataset: Dataset) -> bool | None:
        """Check if a dataset is locked."""
        url = f"{self._base_url}/pool/dataset?id={dataset.path}"

        try:
            response = self.client.get(url, headers=self._headers)
        except httpx.RequestError as e:
            err_console.print(f"[red]Error: {e}[/red]")
            return None

        if response.status_code != 200:
            err_console.print(f"[red]API error {response.status_code}[/red]")
            return None

        try:
            data = response.json()
            locked = data[0].get("locked") if data else None
        except (ValueError, KeyError, IndexError):
            return None

        if locked is True:
            return True
        if locked is False:
            console.print(f"[green]✓[/green] {dataset.path}")
            return False
        return None

    def unlock(self, dataset: Dataset) -> bool:
        """Unlock a dataset."""
        url = f"{self._base_url}/pool/dataset/unlock"
        passphrase = dataset.get_passphrase(self.config.secrets)
        payload = {
            "id": dataset.path,
            "options": {
                "key_file": False,
                "recursive": False,
                "force": True,
                "toggle_attachments": True,
                "datasets": [{"name": dataset.path, "passphrase": passphrase}],
            },
        }

        try:
            response = self.client.post(url, headers=self._headers, json=payload)
        except httpx.RequestError as e:
            err_console.print(f"[red]Error: {e}[/red]")
            return False

        if response.status_code != 200:
            err_console.print(f"[red]API error {response.status_code}[/red]")
            return False

        console.print(f"[blue]→[/blue] Unlocked {dataset.path}")
        return True


def find_config() -> Path | None:
    """Find config file in standard locations."""
    for path in CONFIG_SEARCH_PATHS:
        if path.exists():
            return path
    return None


def run_unlock(config: Config, *, dry_run: bool = False) -> None:
    """Run the unlock process once."""
    if dry_run:
        console.print("[yellow]Dry run:[/yellow]")
        for ds in config.datasets:
            console.print(f"  • {ds.path}")
        return

    client = TrueNasClient(config)
    for dataset in config.datasets:
        if client.is_locked(dataset):
            console.print(f"[yellow]⚡[/yellow] {dataset.path} locked, unlocking...")
            client.unlock(dataset)


app = typer.Typer(
    help="Unlock TrueNAS ZFS datasets",
    no_args_is_help=False,
    add_completion=False,
    context_settings={"help_option_names": ["-h", "--help"]},
)


@app.command()
def main(
    config_path: Annotated[Path | None, typer.Option("--config", "-c", help="Config file path")] = None,
    dry_run: Annotated[bool, typer.Option("--dry-run", "-n", help="Show what would be done")] = False,
    daemon: Annotated[bool, typer.Option("--daemon", "-d", help="Run continuously")] = False,
    interval: Annotated[int, typer.Option("--interval", "-i", help="Seconds between runs")] = 10,
) -> None:
    """Unlock encrypted ZFS datasets on TrueNAS."""
    if config_path is None:
        config_path = find_config()

    if config_path is None or not config_path.exists():
        err_console.print("[red]Config not found.[/red]")
        err_console.print("\nCreate ~/.config/truenas-unlock/config.yaml:\n")
        err_console.print(EXAMPLE_CONFIG)
        raise typer.Exit(1)

    config = Config.from_yaml(config_path)
    console.print(f"[dim]{config_path}[/dim]")

    if daemon:
        console.print(f"[bold]Running every {interval}s[/bold]")
        while True:
            try:
                run_unlock(config, dry_run=dry_run)
                time.sleep(interval)
            except KeyboardInterrupt:
                console.print("\n[bold]Stopped[/bold]")
                break
    else:
        run_unlock(config, dry_run=dry_run)


if __name__ == "__main__":
    app()

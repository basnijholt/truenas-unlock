"""TrueNAS ZFS Dataset Unlock.

Unlocks encrypted ZFS datasets on TrueNAS via the API.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
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

SYSTEMD_SERVICE = """\
[Unit]
Description=TrueNAS Unlock
After=network-online.target
Wants=network-online.target

[Service]
Environment="PATH={path}"
ExecStart={uv_path} tool run truenas-unlock --daemon
Restart=on-failure
RestartSec=10

[Install]
WantedBy=default.target
"""

LAUNCHD_PLIST = """\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" \
"http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.truenas_unlock</string>
  <key>ProgramArguments</key>
  <array>
    <string>{uv_path}</string>
    <string>tool</string>
    <string>run</string>
    <string>truenas-unlock</string>
    <string>--daemon</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>WorkingDirectory</key>
  <string>{home}</string>
  <key>StandardOutPath</key>
  <string>{log_dir}/truenas-unlock.out</string>
  <key>StandardErrorPath</key>
  <string>{log_dir}/truenas-unlock.err</string>
</dict>
</plist>
"""


class SecretsMode(str, Enum):
    """How to interpret secret values."""

    AUTO = "auto"  # check if file exists, otherwise use as literal
    FILES = "files"  # always treat as file paths
    INLINE = "inline"  # always treat as literal values


def resolve_secret(value: str, mode: SecretsMode) -> str:
    """Resolve a secret value based on the secrets mode."""
    if mode == SecretsMode.INLINE:
        return value

    path = Path(value).expanduser()

    if mode == SecretsMode.FILES:
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
    secrets: SecretsMode = SecretsMode.AUTO
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

    def is_locked(self, dataset: Dataset, *, quiet: bool = False) -> bool | None:
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
            if not quiet:
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

    def lock(self, dataset: Dataset, *, force: bool = False) -> bool:
        """Lock a dataset."""
        url = f"{self._base_url}/pool/dataset/lock"
        payload = {
            "id": dataset.path,
            "lock_options": {
                "force_umount": force,
            },
        }

        try:
            response = self.client.post(url, headers=self._headers, json=payload)
        except httpx.RequestError as e:
            err_console.print(f"[red]Error: {e}[/red]")
            return False

        if response.status_code != 200:
            err_console.print(f"[red]API error {response.status_code}: {response.text}[/red]")
            return False

        console.print(f"[yellow]🔒[/yellow] Locked {dataset.path}")
        return True


def find_config() -> Path | None:
    """Find config file in standard locations."""
    for path in CONFIG_SEARCH_PATHS:
        if path.exists():
            return path
    return None


def run_unlock(config: Config, *, dry_run: bool = False, quiet: bool = False) -> None:
    """Run the unlock process once."""
    if dry_run:
        console.print("[yellow]Dry run:[/yellow]")
        for ds in config.datasets:
            console.print(f"  • {ds.path}")
        return

    client = TrueNasClient(config)
    for dataset in config.datasets:
        if client.is_locked(dataset, quiet=quiet):
            console.print(f"[yellow]⚡[/yellow] {dataset.path} locked, unlocking...")
            client.unlock(dataset)


def run_lock(config: Config, *, force: bool = False) -> None:
    """Lock all configured datasets."""
    client = TrueNasClient(config)
    for dataset in config.datasets:
        locked = client.is_locked(dataset, quiet=True)
        if locked is False:
            client.lock(dataset, force=force)
        elif locked is True:
            console.print(f"[dim]Already locked: {dataset.path}[/dim]")


app = typer.Typer(
    help="Unlock TrueNAS ZFS datasets",
    no_args_is_help=False,
    add_completion=False,
    context_settings={"help_option_names": ["-h", "--help"]},
)

service_app = typer.Typer(help="Manage system service", no_args_is_help=True)
app.add_typer(service_app, name="service")


def _get_uv_path() -> Path | None:
    """Find uv executable."""
    uv = shutil.which("uv")
    return Path(uv) if uv else None


def _run(cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run a command and return the result."""
    return subprocess.run(cmd, capture_output=True, text=True, check=check)


@service_app.command("install")
def service_install() -> None:
    """Install and start the system service."""
    uv_path = _get_uv_path()
    if not uv_path:
        err_console.print("[red]Error: uv not found. Install from https://docs.astral.sh/uv/[/red]")
        raise typer.Exit(1)

    # Check config exists
    config_path = find_config()
    if not config_path:
        err_console.print("[yellow]Warning: Config not found.[/yellow]")
        err_console.print("Create ~/.config/truenas-unlock/config.yaml before starting.")

    system = platform.system()

    if system == "Darwin":
        _install_macos(uv_path)
    elif system == "Linux":
        _install_linux(uv_path)
    else:
        err_console.print(f"[red]Unsupported OS: {system}[/red]")
        raise typer.Exit(1)


def _install_macos(uv_path: Path) -> None:
    """Install launchd service on macOS."""
    plist_name = "com.truenas_unlock.plist"
    plist_dst = Path.home() / "Library" / "LaunchAgents" / plist_name
    log_dir = Path.home() / "Library" / "Logs" / "truenas-unlock"

    log_dir.mkdir(parents=True, exist_ok=True)
    plist_dst.parent.mkdir(parents=True, exist_ok=True)

    content = LAUNCHD_PLIST.format(
        uv_path=uv_path,
        home=Path.home(),
        log_dir=log_dir,
    )
    plist_dst.write_text(content)

    _run(["launchctl", "load", str(plist_dst)])

    console.print("[green]✓[/green] Service installed and started")
    console.print(f"  Logs: {log_dir}/")
    console.print("\n  Uninstall: [bold]truenas-unlock service uninstall[/bold]")


def _install_linux(uv_path: Path) -> None:
    """Install systemd user service on Linux."""
    service_name = "truenas-unlock.service"
    service_dir = Path.home() / ".config" / "systemd" / "user"
    service_dst = service_dir / service_name

    service_dir.mkdir(parents=True, exist_ok=True)

    # Pass current PATH to service (needed for NixOS and other non-standard setups)
    current_path = os.environ.get("PATH", "/usr/bin:/bin")
    content = SYSTEMD_SERVICE.format(uv_path=uv_path, path=current_path)
    service_dst.write_text(content)

    _run(["systemctl", "--user", "daemon-reload"])
    _run(["systemctl", "--user", "enable", "--now", "truenas-unlock"])

    console.print("[green]✓[/green] Service installed and started")
    console.print("\n  View logs: [bold]journalctl --user -u truenas-unlock -f[/bold]")
    console.print("  Run at boot: [bold]sudo loginctl enable-linger $USER[/bold]")
    console.print("\n  Uninstall: [bold]truenas-unlock service uninstall[/bold]")


@service_app.command("uninstall")
def service_uninstall() -> None:
    """Stop and remove the system service."""
    system = platform.system()

    if system == "Darwin":
        _uninstall_macos()
    elif system == "Linux":
        _uninstall_linux()
    else:
        err_console.print(f"[red]Unsupported OS: {system}[/red]")
        raise typer.Exit(1)


def _uninstall_macos() -> None:
    """Uninstall launchd service on macOS."""
    plist_dst = Path.home() / "Library" / "LaunchAgents" / "com.truenas_unlock.plist"

    if not plist_dst.exists():
        console.print("Service not installed.")
        return

    _run(["launchctl", "unload", str(plist_dst)], check=False)
    plist_dst.unlink()
    console.print("[green]✓[/green] Service uninstalled")


def _uninstall_linux() -> None:
    """Uninstall systemd user service on Linux."""
    service_dst = Path.home() / ".config" / "systemd" / "user" / "truenas-unlock.service"

    if not service_dst.exists():
        console.print("Service not installed.")
        return

    _run(["systemctl", "--user", "stop", "truenas-unlock"], check=False)
    _run(["systemctl", "--user", "disable", "truenas-unlock"], check=False)
    service_dst.unlink()
    _run(["systemctl", "--user", "daemon-reload"])
    console.print("[green]✓[/green] Service uninstalled")


@service_app.command("status")
def service_status() -> None:
    """Check service status."""
    system = platform.system()

    if system == "Darwin":
        result = _run(["launchctl", "list"], check=False)
        if "com.truenas_unlock" in result.stdout:
            console.print("[green]●[/green] Service is running")
        else:
            console.print("[dim]○[/dim] Service is not running")
    elif system == "Linux":
        result = _run(["systemctl", "--user", "is-active", "truenas-unlock"], check=False)
        if result.stdout.strip() == "active":
            console.print("[green]●[/green] Service is running")
        else:
            console.print("[dim]○[/dim] Service is not running")
    else:
        err_console.print(f"[red]Unsupported OS: {system}[/red]")
        raise typer.Exit(1)


@service_app.command("logs")
def service_logs(
    follow: Annotated[bool, typer.Option("--follow", "-f", help="Follow log output")] = True,
) -> None:
    """View service logs."""
    system = platform.system()

    if system == "Darwin":
        log_dir = Path.home() / "Library" / "Logs" / "truenas-unlock"
        out_log = log_dir / "truenas-unlock.out"
        err_log = log_dir / "truenas-unlock.err"

        if not log_dir.exists():
            err_console.print("[yellow]No logs found. Is the service installed?[/yellow]")
            raise typer.Exit(1)

        cmd = ["tail"]
        if follow:
            cmd.append("-f")
        cmd.extend([str(out_log), str(err_log)])
        os.execvp("tail", cmd)

    elif system == "Linux":
        cmd = ["journalctl", "--user", "-u", "truenas-unlock"]
        if follow:
            cmd.append("-f")
        os.execvp("journalctl", cmd)

    else:
        err_console.print(f"[red]Unsupported OS: {system}[/red]")
        raise typer.Exit(1)


@app.command()
def lock(
    config_path: Annotated[Path | None, typer.Option("--config", "-c", help="Config file path")] = None,
    force: Annotated[bool, typer.Option("--force", "-f", help="Force unmount before locking")] = False,
) -> None:
    """Lock all configured datasets."""
    if config_path is None:
        config_path = find_config()

    if config_path is None or not config_path.exists():
        err_console.print("[red]Config not found.[/red]")
        raise typer.Exit(1)

    config = Config.from_yaml(config_path)
    console.print(f"[dim]{config_path}[/dim]")
    run_lock(config, force=force)


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    config_path: Annotated[Path | None, typer.Option("--config", "-c", help="Config file path")] = None,
    dry_run: Annotated[bool, typer.Option("--dry-run", "-n", help="Show what would be done")] = False,
    daemon: Annotated[bool, typer.Option("--daemon", "-d", help="Run continuously")] = False,
    interval: Annotated[int, typer.Option("--interval", "-i", help="Seconds between runs")] = 10,
) -> None:
    """Unlock encrypted ZFS datasets on TrueNAS."""
    # If a subcommand is invoked, don't run the main logic
    if ctx.invoked_subcommand is not None:
        return

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
                run_unlock(config, dry_run=dry_run, quiet=True)
                time.sleep(interval)
            except KeyboardInterrupt:
                console.print("\n[bold]Stopped[/bold]")
                break
    else:
        run_unlock(config, dry_run=dry_run)


if __name__ == "__main__":
    app()

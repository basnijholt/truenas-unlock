#!/bin/bash
set -e

SERVICE_NAME="truenas-unlock.service"
SERVICE_DST="$HOME/.config/systemd/user/$SERVICE_NAME"
SERVICE_URL="https://raw.githubusercontent.com/basnijholt/truenas-unlock/main/scripts/linux/$SERVICE_NAME"

echo "Installing TrueNAS Unlock service..."

# Find uv path
UV_PATH=$(which uv 2>/dev/null || echo "")
if [ -z "$UV_PATH" ]; then
    echo "Error: uv not found. Install it from https://docs.astral.sh/uv/"
    exit 1
fi
echo "Using uv at: $UV_PATH"

# Check config exists
CONFIG_PATH="$HOME/.config/truenas-unlock/config.yaml"
if [ ! -f "$CONFIG_PATH" ]; then
    echo "Warning: Config not found at $CONFIG_PATH"
    echo "Create it before starting the service."
fi

# Create directory
mkdir -p "$HOME/.config/systemd/user"

# Download service file and replace placeholders
curl -fsSL "$SERVICE_URL" | \
    sed -e "s|<UV-PATH>|$UV_PATH|g" \
    > "$SERVICE_DST"

# Reload and enable
systemctl --user daemon-reload
systemctl --user enable --now truenas-unlock

echo ""
echo "Service installed and started."
echo ""
echo "View logs:"
echo "  journalctl --user -u truenas-unlock -f"
echo ""
echo "To run at boot (without login):"
echo "  sudo loginctl enable-linger \$USER"
echo ""
echo "To uninstall, run:"
echo "  curl -fsSL https://raw.githubusercontent.com/basnijholt/truenas-unlock/main/scripts/linux/uninstall.sh | bash"

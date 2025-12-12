#!/bin/bash
set -e

PLIST_NAME="com.truenas_zfs_unlock.plist"
PLIST_DST="$HOME/Library/LaunchAgents/$PLIST_NAME"
LOG_DIR="$HOME/Library/Logs/truenas-zfs-unlock"
PLIST_URL="https://raw.githubusercontent.com/basnijholt/truenas-zfs-unlock/main/scripts/macos/$PLIST_NAME"

echo "Installing TrueNAS ZFS Unlock service..."

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

# Create directories
mkdir -p "$LOG_DIR"
mkdir -p "$HOME/Library/LaunchAgents"

# Download plist and replace placeholders
curl -fsSL "$PLIST_URL" | \
    sed -e "s|<UV-PATH>|$UV_PATH|g" \
        -e "s|<HOME-DIR>|$HOME|g" \
        -e "s|<LOG-DIR>|$LOG_DIR|g" \
    > "$PLIST_DST"

# Load the service
launchctl load "$PLIST_DST"

echo ""
echo "Service installed and started."
echo "Logs: $LOG_DIR/"
echo ""
echo "To uninstall, run:"
echo "  curl -fsSL https://raw.githubusercontent.com/basnijholt/truenas-zfs-unlock/main/scripts/macos/uninstall.sh | bash"

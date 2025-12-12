#!/bin/bash
set -e

SERVICE_NAME="truenas-unlock.service"
SERVICE_DST="$HOME/.config/systemd/user/$SERVICE_NAME"

echo "Uninstalling TrueNAS Unlock service..."

if [ -f "$SERVICE_DST" ]; then
    systemctl --user stop truenas-unlock 2>/dev/null || true
    systemctl --user disable truenas-unlock 2>/dev/null || true
    rm "$SERVICE_DST"
    systemctl --user daemon-reload
    echo "Service uninstalled."
else
    echo "Service not installed."
fi

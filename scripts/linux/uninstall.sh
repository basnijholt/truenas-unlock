#!/bin/bash
set -e

SERVICE_NAME="truenas-zfs-unlock.service"
SERVICE_DST="$HOME/.config/systemd/user/$SERVICE_NAME"

echo "Uninstalling TrueNAS ZFS Unlock service..."

if [ -f "$SERVICE_DST" ]; then
    systemctl --user stop truenas-zfs-unlock 2>/dev/null || true
    systemctl --user disable truenas-zfs-unlock 2>/dev/null || true
    rm "$SERVICE_DST"
    systemctl --user daemon-reload
    echo "Service uninstalled."
else
    echo "Service not installed."
fi

#!/bin/bash
set -e

PLIST_NAME="com.truenas_zfs_unlock.plist"
PLIST_DST="$HOME/Library/LaunchAgents/$PLIST_NAME"

echo "Uninstalling TrueNAS ZFS Unlock service..."

if [ -f "$PLIST_DST" ]; then
    launchctl unload "$PLIST_DST" 2>/dev/null || true
    rm "$PLIST_DST"
    echo "Service uninstalled."
else
    echo "Service not installed."
fi

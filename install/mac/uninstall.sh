#!/usr/bin/env bash
set -euo pipefail

# GhostLogic Black Box Agent — macOS Uninstaller

INSTALL_DIR="/usr/local/opt/ghostlogic/agent"
CONFIG_DIR="/usr/local/etc/ghostlogic"
LOG_DIR="/usr/local/var/log/ghostlogic"
PLIST_NAME="tech.ghostlogic.agent"
PLIST_FILE="$HOME/Library/LaunchAgents/$PLIST_NAME.plist"

echo ""
echo "=== GhostLogic Agent Uninstaller (macOS) ==="
echo ""

# --- Stop and remove launchd agent ---
if [ -f "$PLIST_FILE" ]; then
    echo "[*] Stopping agent ..."
    launchctl unload "$PLIST_FILE" 2>/dev/null || true
    rm -f "$PLIST_FILE"
    echo "[OK] LaunchAgent removed"
fi

# --- Remove install dir ---
if [ -d "$INSTALL_DIR" ]; then
    echo "[*] Removing $INSTALL_DIR ..."
    rm -rf "$INSTALL_DIR"
    echo "[OK] Removed"
fi

# --- Config and logs ---
if [ -d "$CONFIG_DIR" ] || [ -d "$LOG_DIR" ]; then
    read -rp "Remove config ($CONFIG_DIR) and logs ($LOG_DIR)? [y/N] " answer
    if [ "$answer" = "y" ] || [ "$answer" = "Y" ]; then
        rm -rf "$CONFIG_DIR" "$LOG_DIR"
        echo "[OK] Config and logs removed"
    else
        echo "[*] Config and logs preserved"
    fi
fi

echo ""
echo "=== Uninstall Complete ==="
echo ""

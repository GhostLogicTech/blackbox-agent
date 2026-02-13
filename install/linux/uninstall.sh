#!/usr/bin/env bash
set -euo pipefail

# GhostLogic Black Box Agent — Linux Uninstaller

SERVICE_NAME="ghostlogic-agent"
INSTALL_DIR="/opt/ghostlogic/agent"
CONFIG_DIR="/etc/ghostlogic"
LOG_DIR="/var/log/ghostlogic"

echo ""
echo "=== GhostLogic Agent Uninstaller ==="
echo ""

if [ "$(id -u)" -ne 0 ]; then
    echo "[ERROR] Run as root or with sudo"
    exit 1
fi

# --- Stop and remove service ---
if systemctl is-active --quiet "$SERVICE_NAME" 2>/dev/null; then
    echo "[*] Stopping service ..."
    systemctl stop "$SERVICE_NAME"
fi

if [ -f "/etc/systemd/system/$SERVICE_NAME.service" ]; then
    echo "[*] Removing service ..."
    systemctl disable "$SERVICE_NAME" 2>/dev/null || true
    rm -f "/etc/systemd/system/$SERVICE_NAME.service"
    systemctl daemon-reload
    echo "[OK] Service removed"
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

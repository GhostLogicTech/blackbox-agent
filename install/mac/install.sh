#!/usr/bin/env bash
set -euo pipefail

# GhostLogic Black Box Agent — macOS Installer
# Requires: Python 3.10+

INSTALL_DIR="/usr/local/opt/ghostlogic/agent"
CONFIG_DIR="/usr/local/etc/ghostlogic"
CONFIG_FILE="$CONFIG_DIR/agent-config.json"
LOG_DIR="/usr/local/var/log/ghostlogic"
VENV_DIR="$INSTALL_DIR/venv"
PLIST_NAME="tech.ghostlogic.agent"

BLACKBOX_URL="${BLACKBOX_URL:-https://api.ghostlogic.tech}"
TENANT_KEY="${TENANT_KEY:-}"

# Detect the real user's home even when run with sudo
if [ -n "${SUDO_USER:-}" ]; then
    REAL_HOME=$(eval echo "~$SUDO_USER")
    REAL_USER="$SUDO_USER"
else
    REAL_HOME="$HOME"
    REAL_USER="$(whoami)"
fi
PLIST_FILE="$REAL_HOME/Library/LaunchAgents/$PLIST_NAME.plist"

echo ""
echo "=== GhostLogic Black Box Agent Installer (macOS) ==="
echo ""

# --- Check Python ---
PYTHON=""
for cmd in python3 python; do
    if command -v "$cmd" &>/dev/null; then
        # Use Python itself to report its minor version — robust across all macOS
        minor=$("$cmd" -c "import sys; print(sys.version_info.minor)" 2>/dev/null || echo "0")
        if [ "$minor" -ge 10 ] 2>/dev/null; then
            PYTHON="$cmd"
            echo "[OK] Found $("$cmd" --version 2>&1) ($cmd)"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    echo "[ERROR] Python 3.10+ required."
    echo "  brew install python@3.12"
    echo "  OR download from https://python.org"
    exit 1
fi

# --- Find repo root ---
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

if [ ! -f "$REPO_ROOT/agent/__main__.py" ]; then
    echo "[ERROR] Cannot find agent source at $REPO_ROOT/agent/"
    exit 1
fi

# --- Stop existing agent ---
if [ -f "$PLIST_FILE" ]; then
    echo "[*] Stopping existing agent ..."
    # Try modern bootout first, fall back to legacy unload
    launchctl bootout "gui/$(id -u "$REAL_USER")/$PLIST_NAME" 2>/dev/null \
        || launchctl unload "$PLIST_FILE" 2>/dev/null \
        || true
    sleep 1
fi

# --- Create directories ---
mkdir -p "$INSTALL_DIR" "$CONFIG_DIR" "$LOG_DIR"

# --- Create venv ---
echo "[*] Creating Python venv at $VENV_DIR ..."
"$PYTHON" -m venv "$VENV_DIR"

# --- Copy agent ---
echo "[*] Copying agent files ..."
rm -rf "$INSTALL_DIR/agent"
cp -r "$REPO_ROOT/agent" "$INSTALL_DIR/agent"

# --- Write config (uses Python to generate safe JSON) ---
if [ ! -f "$CONFIG_FILE" ]; then
    AGENT_ID=$("$PYTHON" -c "import uuid; print(uuid.uuid4())")
    "$PYTHON" -c "
import json, sys
config = {
    'blackbox_url': sys.argv[1],
    'tenant_key': sys.argv[2],
    'agent_id': sys.argv[3],
    'collect_interval_secs': 5,
    'seal_interval_secs': 60,
    'demo_mode': True,
    'log_dir': sys.argv[4],
    'log_max_hours': 24,
}
with open(sys.argv[5], 'w') as f:
    json.dump(config, f, indent=2)
" "$BLACKBOX_URL" "$TENANT_KEY" "$AGENT_ID" "$LOG_DIR" "$CONFIG_FILE"
    chmod 600 "$CONFIG_FILE"
    echo "[OK] Config written to $CONFIG_FILE"
else
    echo "[*] Config exists at $CONFIG_FILE — not overwriting"
fi

# --- launchd plist (generated via Python to avoid XML injection) ---
echo "[*] Installing launchd agent: $PLIST_NAME ..."
mkdir -p "$(dirname "$PLIST_FILE")"

"$PYTHON" -c "
import plistlib, sys

plist = {
    'Label': sys.argv[1],
    'ProgramArguments': [
        sys.argv[2],
        '-m', 'agent',
        '--config', sys.argv[3],
    ],
    'WorkingDirectory': sys.argv[4],
    'RunAtLoad': True,
    'KeepAlive': True,
    'StandardOutPath': sys.argv[5] + '/stdout.log',
    'StandardErrorPath': sys.argv[5] + '/stderr.log',
    'EnvironmentVariables': {
        'GHOSTLOGIC_CONFIG': sys.argv[3],
    },
}
with open(sys.argv[6], 'wb') as f:
    plistlib.dump(plist, f)
" "$PLIST_NAME" "$VENV_DIR/bin/python" "$CONFIG_FILE" "$INSTALL_DIR" "$LOG_DIR" "$PLIST_FILE"

# Fix ownership if run with sudo
if [ -n "${SUDO_USER:-}" ]; then
    chown "$SUDO_USER" "$PLIST_FILE"
fi

# Load — try modern bootstrap first, fall back to legacy load
DOMAIN_TARGET="gui/$(id -u "$REAL_USER")"
if launchctl bootstrap "$DOMAIN_TARGET" "$PLIST_FILE" 2>/dev/null; then
    echo "[OK] Agent started (bootstrap)"
elif launchctl load "$PLIST_FILE" 2>/dev/null; then
    echo "[OK] Agent started (load)"
else
    echo "[WARN] Could not start agent. Try manually:"
    echo "  launchctl load $PLIST_FILE"
fi

echo ""
echo "=== Installation Complete ==="
echo "Config:  $CONFIG_FILE"
echo "Logs:    $LOG_DIR"
echo "Agent:   $INSTALL_DIR"
echo "Service: launchctl list | grep ghostlogic"
echo ""
if [ -z "$TENANT_KEY" ]; then
    echo "Edit $CONFIG_FILE to set your tenant_key, then restart:"
    echo "  launchctl kickstart -k $DOMAIN_TARGET/$PLIST_NAME"
fi
echo ""

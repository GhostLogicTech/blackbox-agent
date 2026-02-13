#!/usr/bin/env bash
set -euo pipefail

# GhostLogic Black Box Agent — Linux Installer
# Requires: Python 3.10+, root/sudo

INSTALL_DIR="/opt/ghostlogic/agent"
CONFIG_DIR="/etc/ghostlogic"
CONFIG_FILE="$CONFIG_DIR/agent-config.json"
LOG_DIR="/var/log/ghostlogic"
SERVICE_NAME="ghostlogic-agent"
VENV_DIR="$INSTALL_DIR/venv"

BLACKBOX_URL="${BLACKBOX_URL:-https://api.ghostlogic.tech}"
TENANT_KEY="${TENANT_KEY:-}"

echo ""
echo "=== GhostLogic Black Box Agent Installer ==="
echo ""

# --- Check root ---
if [ "$(id -u)" -ne 0 ]; then
    echo "[ERROR] Run as root or with sudo"
    exit 1
fi

# --- Check Python ---
PYTHON=""
for cmd in python3 python; do
    if command -v "$cmd" &>/dev/null; then
        full_ver=$("$cmd" --version 2>&1)
        # Extract minor version robustly
        minor=$("$cmd" -c "import sys; print(sys.version_info.minor)" 2>/dev/null || echo "0")
        if [ "$minor" -ge 10 ] 2>/dev/null; then
            PYTHON="$cmd"
            echo "[OK] Found $full_ver ($cmd)"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    echo "[ERROR] Python 3.10+ required."
    echo "  Ubuntu/Debian: sudo apt install python3 python3-venv"
    echo "  RHEL/Fedora:   sudo dnf install python3"
    exit 1
fi

# --- Check venv module ---
if ! "$PYTHON" -m venv --help &>/dev/null; then
    echo "[ERROR] python3-venv not installed."
    echo "  Ubuntu/Debian: sudo apt install python3-venv"
    exit 1
fi

# --- Find repo root ---
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

if [ ! -f "$REPO_ROOT/agent/__main__.py" ]; then
    echo "[ERROR] Cannot find agent source at $REPO_ROOT/agent/"
    exit 1
fi

# --- Stop existing service before upgrade ---
if systemctl is-active --quiet "$SERVICE_NAME" 2>/dev/null; then
    echo "[*] Stopping existing service for upgrade ..."
    systemctl stop "$SERVICE_NAME"
fi

# --- Create directories ---
mkdir -p "$INSTALL_DIR" "$CONFIG_DIR" "$LOG_DIR"
chmod 700 "$CONFIG_DIR"

# --- Create venv ---
echo "[*] Creating Python venv at $VENV_DIR ..."
"$PYTHON" -m venv "$VENV_DIR"

# --- Copy agent ---
echo "[*] Copying agent files ..."
rm -rf "$INSTALL_DIR/agent"
cp -r "$REPO_ROOT/agent" "$INSTALL_DIR/agent"

# --- Write config (uses Python to safely generate JSON, no heredoc injection) ---
if [ ! -f "$CONFIG_FILE" ]; then
    AGENT_ID=$(cat /proc/sys/kernel/random/uuid 2>/dev/null || "$PYTHON" -c "import uuid; print(uuid.uuid4())")
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

# --- systemd unit ---
echo "[*] Installing systemd service: $SERVICE_NAME ..."
cat > "/etc/systemd/system/$SERVICE_NAME.service" <<'UNITEOF'
[Unit]
Description=GhostLogic Black Box Agent
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
UNITEOF

# Append paths (these are safe system paths, not user input)
cat >> "/etc/systemd/system/$SERVICE_NAME.service" <<EOF
ExecStart=$VENV_DIR/bin/python -m agent --config $CONFIG_FILE
WorkingDirectory=$INSTALL_DIR
Environment=GHOSTLOGIC_CONFIG=$CONFIG_FILE
EOF

cat >> "/etc/systemd/system/$SERVICE_NAME.service" <<'UNITEOF'
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
UNITEOF

systemctl daemon-reload
systemctl enable "$SERVICE_NAME"

if systemctl start "$SERVICE_NAME"; then
    echo "[OK] Service started"
else
    echo "[WARN] Service failed to start — check: journalctl -u $SERVICE_NAME -n 20"
fi

echo ""
echo "=== Installation Complete ==="
echo "Config:  $CONFIG_FILE"
echo "Logs:    $LOG_DIR"
echo "Agent:   $INSTALL_DIR"
echo "Service: systemctl status $SERVICE_NAME"
echo ""
if [ -z "$TENANT_KEY" ]; then
    echo "Edit $CONFIG_FILE to set your tenant_key, then:"
    echo "  sudo systemctl restart $SERVICE_NAME"
fi
echo ""

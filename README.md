# GhostLogic Black Box Agent

Lightweight endpoint telemetry agent. Collects system info every 5 seconds, sends it to a GhostLogic Black Box server, and seals evidence capsules every 60 seconds.

**No Docker. No kernel hooks. No external dependencies.** Python 3.10+ standard library only.

## What it collects

- Hostname, OS, version, username
- Top 20 processes
- Network connections summary (listening/established counts)
- Uptime
- CPU usage %
- RAM usage %

All data is normalized into GhostLogic event JSON and sent via HTTPS.

## Supported platforms

- Windows 10/11
- Ubuntu 22.04 / 24.04
- macOS (basic support)

---

## Quickstart

### 1. Get your tenant key

Log into the [GhostLogic Console](https://console.ghostlogic.tech) and go to **Settings** to generate a tenant key.

### 2. Install

**Linux (Ubuntu/Debian):**

```bash
git clone https://github.com/GhostLogicAI/blackbox-agent.git
cd blackbox-agent
sudo TENANT_KEY="your-key-here" bash install/linux/install.sh
```

**Windows (PowerShell as Administrator):**

```powershell
git clone https://github.com/GhostLogicAI/blackbox-agent.git
cd blackbox-agent
.\install\windows\install.ps1 -TenantKey "your-key-here"
```

**macOS:**

```bash
git clone https://github.com/GhostLogicAI/blackbox-agent.git
cd blackbox-agent
TENANT_KEY="your-key-here" bash install/mac/install.sh
```

### 3. Run manually (no install)

```bash
python -m agent --config examples/agent-config.example.json --demo
```

---

## Configuration

Config file location:

| Platform | Path |
|----------|------|
| Linux    | `/etc/ghostlogic/agent-config.json` |
| Windows  | `C:\ProgramData\GhostLogic\agent-config.json` |
| macOS    | `/usr/local/etc/ghostlogic/agent-config.json` |

Override with `--config /path/to/file.json` or env `GHOSTLOGIC_CONFIG=/path/to/file.json`.

### Fields

```json
{
  "blackbox_url": "https://api.blackbox.ghostlogic.tech",
  "tenant_key": "YOUR_TENANT_KEY",
  "agent_id": "auto-generated-uuid",
  "collect_interval_secs": 5,
  "seal_interval_secs": 60,
  "demo_mode": true,
  "log_dir": "/var/log/ghostlogic",
  "log_max_hours": 24
}
```

| Field | Description |
|-------|-------------|
| `blackbox_url` | Black Box API endpoint |
| `tenant_key` | Auth key from Console Settings |
| `agent_id` | Auto-generated. Identifies this agent instance |
| `collect_interval_secs` | How often to collect + send telemetry (seconds) |
| `seal_interval_secs` | How often to seal an evidence capsule (seconds) |
| `demo_mode` | `true` = skip TLS cert verification. Set `false` for production |
| `log_dir` | Where rolling log files go |
| `log_max_hours` | How many hours of logs to keep |

### Security

- Config file is created with `600` permissions (owner-only) on Linux/macOS
- Config file ACL is restricted to Administrators on Windows
- Tenant key is never printed in logs
- Tenant key is scrubbed from error messages before logging

---

## API endpoints used

| Method | Endpoint | Interval | Purpose |
|--------|----------|----------|---------|
| POST | `/api/v1/ingest` | Every 5s | Send telemetry events |
| POST | `/api/v1/seal` | Every 60s | Seal evidence capsule |

Auth: `Authorization: Bearer <tenant_key>` and `X-API-Key: <tenant_key>` headers.

---

## Uninstall

**Linux:**

```bash
sudo bash install/linux/uninstall.sh
```

**Windows (PowerShell as Administrator):**

```powershell
.\install\windows\uninstall.ps1
```

**macOS:**

```bash
bash install/mac/uninstall.sh
```

---

## Troubleshooting

### Agent won't start

1. Check Python version: `python3 --version` (need 3.10+)
2. Check config exists and is valid JSON
3. Check logs:
   - Linux: `journalctl -u ghostlogic-agent -f`
   - Windows: `C:\ProgramData\GhostLogic\logs\ghostlogic-agent.log`
   - macOS: `/usr/local/var/log/ghostlogic/stderr.log`

### Connection errors

1. Verify `blackbox_url` is correct
2. Test connectivity: `curl -s https://api.blackbox.ghostlogic.tech/health`
3. If using self-signed certs, set `demo_mode: true`

### "No tenant_key configured"

Edit your config file and add the tenant key from Console Settings. Then restart the service.

### Service management

```bash
# Linux
sudo systemctl status ghostlogic-agent
sudo systemctl restart ghostlogic-agent
sudo systemctl stop ghostlogic-agent
sudo journalctl -u ghostlogic-agent -f

# macOS
launchctl list | grep ghostlogic
launchctl unload ~/Library/LaunchAgents/tech.ghostlogic.agent.plist
launchctl load ~/Library/LaunchAgents/tech.ghostlogic.agent.plist

# Windows (PowerShell as Admin)
Get-ScheduledTask -TaskName GhostLogicAgent
Start-ScheduledTask -TaskName GhostLogicAgent
Stop-ScheduledTask -TaskName GhostLogicAgent
```

---

## Repo structure

```
blackbox-agent/
  README.md
  LICENSE
  .gitignore
  requirements.txt
  agent/
    __init__.py
    __main__.py        # Entry point
    collector.py       # System telemetry collection
    normalize.py       # Raw data -> GhostLogic event schema
    client.py          # HTTP client for Black Box API
    config.py          # Config loading + validation
    loop.py            # Main agent loop
    log.py             # Rolling file logger
  install/
    windows/
      install.ps1
      uninstall.ps1
    linux/
      install.sh
      uninstall.sh
    mac/
      install.sh
      uninstall.sh
  examples/
    agent-config.example.json
```

---

## Standalone binary (future)

PyInstaller packaging is planned but not implemented. For now, use the Python venv install.

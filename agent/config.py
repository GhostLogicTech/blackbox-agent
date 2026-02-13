"""Configuration loader for GhostLogic Agent."""

import json
import os
import platform
import stat
import sys
import uuid


DEFAULT_CONFIG = {
    "blackbox_url": "https://api.blackbox.ghostlogic.tech",
    "tenant_key": "",
    "agent_id": "",
    "collect_interval_secs": 5,
    "seal_interval_secs": 60,
    "demo_mode": True,
    "log_dir": "",
    "log_max_hours": 24,
}


def _default_config_path() -> str:
    system = platform.system()
    if system == "Windows":
        base = os.environ.get("PROGRAMDATA", r"C:\ProgramData")
        return os.path.join(base, "GhostLogic", "agent-config.json")
    elif system == "Darwin":
        return "/usr/local/etc/ghostlogic/agent-config.json"
    else:
        return "/etc/ghostlogic/agent-config.json"


def _default_log_dir() -> str:
    system = platform.system()
    if system == "Windows":
        base = os.environ.get("PROGRAMDATA", r"C:\ProgramData")
        return os.path.join(base, "GhostLogic", "logs")
    elif system == "Darwin":
        return "/usr/local/var/log/ghostlogic"
    else:
        return "/var/log/ghostlogic"


def load_config(path: str | None = None) -> dict:
    """Load config from file. Falls back to defaults if missing."""
    if path is None:
        path = os.environ.get("GHOSTLOGIC_CONFIG", _default_config_path())

    config = dict(DEFAULT_CONFIG)

    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as f:
            user_config = json.load(f)
        config.update(user_config)
    else:
        # Write default config so user can edit it
        parent = os.path.dirname(path)
        try:
            os.makedirs(parent, exist_ok=True)
        except PermissionError:
            print(f"[config] Cannot create {parent} — run as root/admin or specify --config", file=sys.stderr)
            return config

        default_with_id = dict(DEFAULT_CONFIG)
        default_with_id["agent_id"] = str(uuid.uuid4())

        if platform.system() != "Windows":
            # On unix: create file with restricted permissions atomically
            # using os.open with mode flags so the file is never world-readable
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(default_with_id, f, indent=2)
        else:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(default_with_id, f, indent=2)

        config = default_with_id
        print(f"[config] Created default config at {path}", file=sys.stderr)
        print(f"[config] Edit this file to set your tenant_key and blackbox_url", file=sys.stderr)

    # Generate agent_id if missing
    if not config.get("agent_id"):
        config["agent_id"] = str(uuid.uuid4())

    # Set default log dir if empty
    if not config.get("log_dir"):
        config["log_dir"] = _default_log_dir()

    return config


def validate_config(config: dict) -> list[str]:
    """Return list of config problems. Empty list means OK."""
    problems = []
    if not config.get("tenant_key"):
        problems.append("tenant_key is empty — agent will not authenticate")
    if not config.get("blackbox_url"):
        problems.append("blackbox_url is empty")
    if config.get("collect_interval_secs", 0) < 1:
        problems.append("collect_interval_secs must be >= 1")
    if config.get("seal_interval_secs", 0) < 5:
        problems.append("seal_interval_secs must be >= 5")
    return problems

"""GhostLogic Black Box Agent — entry point.

Usage:
    ghostlogic-agent                          # pip-installed CLI
    python -m agent                           # from repo
    python -m agent --config /path/to/config.json
    python -m agent --demo
"""

import argparse
import socket
import sys

from .config import load_config, save_config, validate_config
from .client import register
from .log import setup_logging
from .loop import run

BANNER = r"""
   ____  _                 _   _                 _
  / ___|| |__   ___   ___| |_| |    ___   __ _ (_) ___
 | |  _ | '_ \ / _ \ / __| __| |   / _ \ / _` || |/ __|
 | |_| || | | | (_) |\__ \ |_| |__| (_) | (_| || | (__
  \____||_| |_|\___/ |___/\__|_____\___/ \__, ||_|\___|
                                         |___/
        Black Box Agent v1.1.0
"""

KEY_BANNER = """
================================================================
|                                                              |
|   YOUR API KEY (paste this into the Black Box Console):      |
|                                                              |
|   {key}
|                                                              |
|   Config saved to: {path}
|                                                              |
================================================================
"""


def _auto_register(config: dict) -> bool:
    """Register with the Black Box API and save the key. Returns True on success."""
    base_url = config.get("blackbox_url", "https://api.ghostlogic.tech")
    demo_mode = config.get("demo_mode", False)
    hostname = socket.gethostname()

    print(f"[register] No API key found. Registering as '{hostname}' ...")

    result = register(base_url, hostname, demo_mode)

    if "api_key" in result:
        api_key = result["api_key"]
        config["tenant_key"] = api_key
        save_config(config)

        path = config.get("_config_path", "?")
        print(KEY_BANNER.format(key=api_key, path=path))
        return True
    else:
        detail = result.get("detail", result)
        print(f"[register] Registration failed: {detail}", file=sys.stderr)
        print("[register] Set tenant_key manually in your config file.", file=sys.stderr)
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="GhostLogic Black Box Agent")
    parser.add_argument("--config", "-c", help="Path to config JSON file")
    parser.add_argument("--demo", action="store_true", help="Force demo mode")
    args = parser.parse_args()

    print(BANNER)

    config = load_config(args.config)

    if args.demo:
        config["demo_mode"] = True

    logger = setup_logging(config["log_dir"], config.get("log_max_hours", 24))

    # Auto-register if no tenant key
    if not config.get("tenant_key"):
        if not _auto_register(config):
            logger.error("Cannot start without an API key. Exiting.")
            sys.exit(1)

    problems = validate_config(config)
    for p in problems:
        logger.warning("Config: %s", p)

    try:
        run(config)
    except KeyboardInterrupt:
        logger.info("Agent stopped by user")
        sys.exit(0)


if __name__ == "__main__":
    main()

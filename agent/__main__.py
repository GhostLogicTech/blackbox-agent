"""GhostLogic Black Box Agent — entry point.

Usage:
    python -m agent
    python -m agent --config /path/to/config.json
    python -m agent --demo
"""

import argparse
import sys

from .config import load_config, validate_config
from .log import setup_logging
from .loop import run

BANNER = r"""
   ____  _                 _   _                 _
  / ___|| |__   ___   ___| |_| |    ___   __ _ (_) ___
 | |  _ | '_ \ / _ \ / __| __| |   / _ \ / _` || |/ __|
 | |_| || | | | (_) |\__ \ |_| |__| (_) | (_| || | (__
  \____||_| |_|\___/ |___/\__|_____\___/ \__, ||_|\___|
                                         |___/
        Black Box Agent v1.0.0
"""


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

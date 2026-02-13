"""Rolling file logger. Keeps last N hours of logs."""

import logging
import os
import time
import glob
from logging.handlers import TimedRotatingFileHandler


def setup_logging(log_dir: str, max_hours: int = 24) -> logging.Logger:
    """Set up rolling file + stderr logging. Returns root logger."""
    os.makedirs(log_dir, exist_ok=True)

    log_file = os.path.join(log_dir, "ghostlogic-agent.log")

    root = logging.getLogger("ghostlogic")
    root.setLevel(logging.DEBUG)

    # File handler: rotate every hour, keep max_hours backups
    fh = TimedRotatingFileHandler(
        log_file,
        when="h",
        interval=1,
        backupCount=max_hours,
        encoding="utf-8",
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    ))
    root.addHandler(fh)

    # Stderr handler
    sh = logging.StreamHandler()
    sh.setLevel(logging.INFO)
    sh.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    ))
    root.addHandler(sh)

    return root


def scrub_sensitive(msg: str, tenant_key: str) -> str:
    """Remove tenant key from a string before logging."""
    if tenant_key and tenant_key in msg:
        return msg.replace(tenant_key, "[REDACTED]")
    return msg

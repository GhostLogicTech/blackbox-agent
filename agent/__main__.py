"""GhostLogic Black Box Agent — entry point.

Usage:
    ghostlogic-agent                          # pip-installed CLI
    python -m agent                           # from repo
    python -m agent --config /path/to/config.json
    python -m agent --demo
    python -m agent --foreground               # stay in foreground (don't daemonize)
"""

import argparse
import os
import platform
import socket
import subprocess
import sys
import webbrowser

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

RUNNING_MSG = """
Agent is now running in the background.
  Config:  {config_path}
  Logs:    {log_dir}
  PID:     {pid}

Paste your API key at https://blackbox.ghostlogic.tech
To stop:  ghostlogic-agent --stop
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

        # Open the console so user can paste the key right away
        try:
            webbrowser.open("https://blackbox.ghostlogic.tech")
        except Exception:
            pass  # headless / no browser is fine

        return True
    else:
        detail = result.get("detail", result)
        print(f"[register] Registration failed: {detail}", file=sys.stderr)
        print("[register] Set tenant_key manually in your config file.", file=sys.stderr)
        return False


def _pid_file_path(config: dict) -> str:
    """Return path to the PID file."""
    log_dir = config.get("log_dir", "")
    if log_dir:
        return os.path.join(log_dir, "ghostlogic-agent.pid")
    if platform.system() == "Windows":
        base = os.environ.get("PROGRAMDATA", r"C:\ProgramData")
        return os.path.join(base, "GhostLogic", "ghostlogic-agent.pid")
    return "/tmp/ghostlogic-agent.pid"


def _stop_agent(config: dict) -> None:
    """Stop a running background agent."""
    pid_path = _pid_file_path(config)
    if not os.path.isfile(pid_path):
        print("No running agent found (no PID file).")
        return

    with open(pid_path, "r") as f:
        pid = int(f.read().strip())

    try:
        if platform.system() == "Windows":
            subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                           capture_output=True, check=True)
        else:
            import signal
            os.kill(pid, signal.SIGTERM)
        print(f"Agent (PID {pid}) stopped.")
    except (ProcessLookupError, subprocess.CalledProcessError):
        print(f"Agent (PID {pid}) was not running.")

    try:
        os.remove(pid_path)
    except OSError:
        pass


def _spawn_background(args_config: str | None, demo: bool) -> int:
    """Re-launch this agent as a detached background process. Returns child PID."""
    python = sys.executable
    cmd = [python, "-m", "agent", "--foreground"]
    if args_config:
        cmd += ["--config", args_config]
    if demo:
        cmd.append("--demo")

    if platform.system() == "Windows":
        # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        flags = 0x00000008 | 0x00000200
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            creationflags=flags,
        )
    else:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )

    return proc.pid


def main() -> None:
    parser = argparse.ArgumentParser(description="GhostLogic Black Box Agent")
    parser.add_argument("--config", "-c", help="Path to config JSON file")
    parser.add_argument("--demo", action="store_true", help="Force demo mode")
    parser.add_argument("--foreground", action="store_true",
                        help="Run in foreground (don't daemonize)")
    parser.add_argument("--stop", action="store_true",
                        help="Stop a running background agent")
    args = parser.parse_args()

    print(BANNER)

    config = load_config(args.config)

    if args.demo:
        config["demo_mode"] = True

    # Handle --stop
    if args.stop:
        _stop_agent(config)
        return

    # Auto-register if no tenant key (always foreground for this part)
    if not config.get("tenant_key"):
        logger = setup_logging(config["log_dir"], config.get("log_max_hours", 24))
        if not _auto_register(config):
            logger.error("Cannot start without an API key. Exiting.")
            sys.exit(1)

    # If not --foreground, spawn background and exit
    if not args.foreground:
        pid = _spawn_background(args.config, args.demo)

        # Write PID file
        pid_path = _pid_file_path(config)
        os.makedirs(os.path.dirname(pid_path), exist_ok=True)
        with open(pid_path, "w") as f:
            f.write(str(pid))

        print(RUNNING_MSG.format(
            config_path=config.get("_config_path", "?"),
            log_dir=config.get("log_dir", "?"),
            pid=pid,
        ))
        return

    # --foreground: run the agent loop directly
    logger = setup_logging(config["log_dir"], config.get("log_max_hours", 24))

    # Write PID file for --stop
    pid_path = _pid_file_path(config)
    os.makedirs(os.path.dirname(pid_path), exist_ok=True)
    with open(pid_path, "w") as f:
        f.write(str(os.getpid()))

    problems = validate_config(config)
    for p in problems:
        logger.warning("Config: %s", p)

    try:
        run(config)
    except KeyboardInterrupt:
        logger.info("Agent stopped by user")
    finally:
        try:
            os.remove(pid_path)
        except OSError:
            pass
        sys.exit(0)


if __name__ == "__main__":
    main()
